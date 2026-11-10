import { reactive, computed } from 'vue';
import { API_BASE, getAuthHeader, tryRefreshToken } from '../services/api.js';

const STORAGE_KEY = 'bomapos_offline_orders';

// Load stored offline queue
function loadStoredQueue() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('[OfflineQueue] Failed to parse stored queue:', e);
    return [];
  }
}

function persistQueue(queue) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch (e) {
    console.error('[OfflineQueue] Failed to save queue to localStorage:', e);
  }
}

export const offlineQueue = reactive({
  isOnline: navigator.onLine,
  isSimulatedOffline: false,
  isSyncing: false,
  needsReauth: false,
  lastSyncTime: null,
  lastSyncResult: null,
  queue: loadStoredQueue(),

  // Computed effective online state (considers real network + manual test simulation)
  effectiveOnline: computed(() => {
    return offlineQueue.isOnline && !offlineQueue.isSimulatedOffline;
  }),

  queuedCount: computed(() => {
    return offlineQueue.queue.length;
  }),

  hasPendingOrders: computed(() => {
    return offlineQueue.queue.length > 0;
  }),

  // Toggle simulated offline mode for seamless testing without pulling network cables
  toggleSimulatedOffline() {
    offlineQueue.isSimulatedOffline = !offlineQueue.isSimulatedOffline;
    if (!offlineQueue.isSimulatedOffline && offlineQueue.isOnline) {
      // Reconnected! Automatically flush queue
      setTimeout(() => {
        offlineQueue.syncQueue();
      }, 400);
    }
  },

  // Save an order locally
  enqueueOrder(payload, itemsDetail = []) {
    const localId = `OFFLINE-${Date.now().toString().slice(-6)}-${Math.floor(Math.random() * 899 + 100)}`;

    const cleanPayload = { ...payload };
    delete cleanPayload.cashier_id;

    // Calculate total amount from itemsDetail
    const totalAmount = itemsDetail.reduce(
      (sum, item) => sum + (item.price_zmw || item.price || 0) * (item.quantity || 1),
      0
    );

    const queuedRecord = {
      localId,
      payload: cleanPayload,
      itemsDetail: itemsDetail.map((i) => ({
        id: i.id,
        name: i.name,
        price_zmw: i.price_zmw,
        quantity: i.quantity,
        category: i.category,
      })),
      totalAmount: Math.round(totalAmount * 100) / 100,
      createdAt: new Date().toISOString(),
      timestampStr: new Date().toLocaleTimeString(),
      status: 'pending',
      retryCount: 0,
    };

    offlineQueue.queue.push(queuedRecord);
    persistQueue(offlineQueue.queue);

    console.log(`[OfflineQueue] Order ${localId} queued offline. Queue count: ${offlineQueue.queue.length}`);

    // Return mock response matching backend OrderResponse contract
    return {
      id: localId,
      is_offline: true,
      total_amount: queuedRecord.totalAmount,
      payment_method: cleanPayload.payment_method,
      payment_status: cleanPayload.payment_method === 'cash' ? 'paid (offline)' : 'pending (offline)',
      created_at: queuedRecord.createdAt,
      items: queuedRecord.itemsDetail,
      message: 'Saved offline. Will sync when online.',
    };
  },

  // Process & flush queued orders to the FastAPI backend
  async syncQueue() {
    if (!offlineQueue.effectiveOnline) {
      console.log('[OfflineQueue] Cannot sync while offline.');
      return { success: false, reason: 'offline' };
    }

    if (offlineQueue.isSyncing || offlineQueue.queue.length === 0) {
      return { success: true, count: 0 };
    }

    offlineQueue.isSyncing = true;
    offlineQueue.lastSyncResult = null;
    offlineQueue.needsReauth = false;
    let syncedCount = 0;
    const remainingQueue = [];

    console.log(`[OfflineQueue] Beginning background sync for ${offlineQueue.queue.length} order(s)...`);

    for (let i = 0; i < offlineQueue.queue.length; i++) {
      const order = offlineQueue.queue[i];
      try {
        const cleanPayload = { ...order.payload };
        delete cleanPayload.cashier_id;

        let response = await fetch(`${API_BASE}/api/orders`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...getAuthHeader(),
          },
          body: JSON.stringify(cleanPayload),
        });

        // If access token expired during offline window, attempt refresh once
        if (response.status === 401) {
          const refreshed = await tryRefreshToken();
          if (refreshed) {
            response = await fetch(`${API_BASE}/api/orders`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                ...getAuthHeader(),
              },
              body: JSON.stringify(cleanPayload),
            });
          }
        }

        if (response.ok) {
          const result = await response.json();
          syncedCount++;
          console.log(`[OfflineQueue] Order ${order.localId} successfully synced -> Server Ticket #${result.id}`);
        } else if (response.status === 401) {
          // Critical: Expired/revoked token must NEVER discard queued orders.
          // Preserve this order and all subsequent orders in pending state to flush after re-authentication.
          console.warn(`[OfflineQueue] Token expired while syncing ${order.localId}. Keeping ${offlineQueue.queue.length - i} order(s) queued until re-authentication.`);
          offlineQueue.needsReauth = true;
          for (let j = i; j < offlineQueue.queue.length; j++) {
            offlineQueue.queue[j].status = 'pending_auth';
            remainingQueue.push(offlineQueue.queue[j]);
          }
          break;
        } else {
          // Non-auth server error (e.g. 400 Bad Request), keep in queue for inspection
          const errData = await response.json().catch(() => ({}));
          console.error(`[OfflineQueue] Sync failed for ${order.localId}:`, errData);
          order.retryCount = (order.retryCount || 0) + 1;
          order.status = 'failed';
          order.lastError = errData.detail || `HTTP ${response.status}`;
          remainingQueue.push(order);
        }
      } catch (networkErr) {
        console.warn(`[OfflineQueue] Network error syncing ${order.localId}. Aborting sync cycle.`, networkErr);
        for (let j = i; j < offlineQueue.queue.length; j++) {
          remainingQueue.push(offlineQueue.queue[j]);
        }
        break;
      }
    }

    offlineQueue.queue = remainingQueue;
    persistQueue(offlineQueue.queue);
    offlineQueue.isSyncing = false;
    offlineQueue.lastSyncTime = new Date().toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });

    if (syncedCount > 0) {
      offlineQueue.lastSyncResult = `Successfully synced ${syncedCount} offline order${syncedCount > 1 ? 's' : ''} to database.`;
      window.dispatchEvent(new CustomEvent('bomapos:queue-synced', { detail: { count: syncedCount } }));
    }

    return {
      success: !offlineQueue.needsReauth,
      syncedCount,
      remainingCount: remainingQueue.length,
      needsReauth: offlineQueue.needsReauth,
    };
  },

  // Clear failed orders or wipe queue manually
  clearQueue() {
    offlineQueue.queue = [];
    persistQueue(offlineQueue.queue);
  },
});

// Window Online/Offline Event Listeners
window.addEventListener('online', () => {
  console.log('[OfflineQueue] Window "online" event received. Network restored.');
  offlineQueue.isOnline = true;
  setTimeout(() => {
    offlineQueue.syncQueue();
  }, 600);
});

window.addEventListener('offline', () => {
  console.log('[OfflineQueue] Window "offline" event received. Device went offline.');
  offlineQueue.isOnline = false;
});
