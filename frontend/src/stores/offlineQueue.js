import { reactive, computed } from 'vue';

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
    
    // Calculate total amount from itemsDetail
    const totalAmount = itemsDetail.reduce(
      (sum, item) => sum + (item.price_zmw || item.price || 0) * (item.quantity || 1),
      0
    );

    const queuedRecord = {
      localId,
      payload: { ...payload },
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
      cashier_id: payload.cashier_id,
      total_amount: queuedRecord.totalAmount,
      payment_method: payload.payment_method,
      payment_status: payload.payment_method === 'cash' ? 'paid (offline)' : 'pending (offline)',
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
    let syncedCount = 0;
    const remainingQueue = [];

    const token = localStorage.getItem('bomapos_token');
    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Auth-Token': token } : {}),
    };

    console.log(`[OfflineQueue] Beginning background sync for ${offlineQueue.queue.length} order(s)...`);

    for (const order of offlineQueue.queue) {
      try {
        const response = await fetch('http://localhost:8000/api/orders', {
          method: 'POST',
          headers,
          body: JSON.stringify(order.payload),
        });

        if (response.ok) {
          const result = await response.json();
          syncedCount++;
          console.log(`[OfflineQueue] Order ${order.localId} successfully synced -> Server Ticket #${result.id}`);
        } else {
          // If server returned non-200 (e.g. 400 Bad Request or 401 Unauthorized), log and keep for inspection
          const errData = await response.json().catch(() => ({}));
          console.error(`[OfflineQueue] Sync failed for ${order.localId}:`, errData);
          order.retryCount = (order.retryCount || 0) + 1;
          order.status = 'failed';
          order.lastError = errData.detail || `HTTP ${response.status}`;
          remainingQueue.push(order);
        }
      } catch (networkErr) {
        console.warn(`[OfflineQueue] Network error syncing ${order.localId}. Aborting sync cycle.`, networkErr);
        // Put current and all subsequent orders back into remainingQueue
        remainingQueue.push(order);
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
      // Dispatch custom DOM event so views can refresh menu/analytics
      window.dispatchEvent(new CustomEvent('bomapos:queue-synced', { detail: { count: syncedCount } }));
    }

    return { success: true, syncedCount, remainingCount: remainingQueue.length };
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
  // Delay slightly to ensure network stack is fully ready
  setTimeout(() => {
    offlineQueue.syncQueue();
  }, 600);
});

window.addEventListener('offline', () => {
  console.log('[OfflineQueue] Window "offline" event received. Device went offline.');
  offlineQueue.isOnline = false;
});
