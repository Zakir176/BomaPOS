import { offlineQueue } from '../stores/offlineQueue.js';

const API_BASE = 'http://localhost:8000';

function getAuthHeader() {
  const token = localStorage.getItem('bomapos_token');
  return token ? { 'X-Auth-Token': token } : {};
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeader(),
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, { ...options, headers });
    const data = await res.json().catch(() => null);

    if (!res.ok) {
      const errorMsg = data?.detail || `HTTP Error ${res.status}`;
      throw new Error(errorMsg);
    }
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

export const api = {
  // Auth
  login: (username, password) =>
    request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  // Menu (With offline fallback caching)
  getMenu: async () => {
    try {
      const data = await request('/api/menu');
      try {
        localStorage.setItem('bomapos_cached_menu', JSON.stringify(data));
      } catch (e) {}
      return data;
    } catch (err) {
      const cached = localStorage.getItem('bomapos_cached_menu');
      if (cached) {
        console.log('[API] Serving menu from local fallback cache');
        return JSON.parse(cached);
      }
      throw err;
    }
  },

  updateMenuItem: (itemId, payload) =>
    request(`/api/menu/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // Drink Inventory
  getDrinkInventory: () => request('/api/inventory/drinks'),
  updateDrinkInventory: (drinkId, payload) =>
    request(`/api/inventory/drinks/${drinkId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // Orders (With Offline Queue Interception & Fallback)
  createOrder: async (payload, itemsDetail = []) => {
    // 1. If currently offline (or in simulated offline mode), intercept immediately
    if (!offlineQueue.effectiveOnline) {
      console.log('[API] Client is offline. Intercepting order creation to offline queue.');
      return offlineQueue.enqueueOrder(payload, itemsDetail);
    }

    // 2. Attempt online network creation
    try {
      return await request('/api/orders', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    } catch (err) {
      // 3. If network fails during request (e.g. WiFi dropped mid-flight), fallback to queue
      const isNetworkIssue =
        !navigator.onLine ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('network');

      if (isNetworkIssue) {
        console.warn('[API] Network failure while posting order. Saving to offline queue.');
        return offlineQueue.enqueueOrder(payload, itemsDetail);
      }
      throw err;
    }
  },

  // Mobile Money
  initiateMobileMoney: (orderId, phone, operator) =>
    request('/api/payments/mobile-money/initiate', {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, phone, operator }),
    }),

  pollPaymentStatus: (lencoReference) =>
    request(`/api/payments/status/${lencoReference}`),

  // Dev Webhook Simulation
  simulateLencoWebhook: (lencoReference, status) =>
    request('/api/webhooks/lenco', {
      method: 'POST',
      body: JSON.stringify({ lenco_reference: lencoReference, status }),
    }),

  // Dashboard
  getDashboardSummary: () => request('/api/dashboard/summary'),
  getDashboardCalendar: (month, year) => {
    const params = new URLSearchParams();
    if (month) params.append('month', month);
    if (year) params.append('year', year);
    const query = params.toString() ? `?${params.toString()}` : '';
    return request(`/api/dashboard/calendar${query}`);
  },
};
