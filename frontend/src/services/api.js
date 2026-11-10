import { offlineQueue } from '../stores/offlineQueue.js';

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export function getAuthHeader() {
  const token = localStorage.getItem('bomapos_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

let refreshPromise = null;

export async function tryRefreshToken() {
  if (refreshPromise) return refreshPromise;

  const refreshToken = localStorage.getItem('bomapos_refresh_token');
  if (!refreshToken) return false;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (data?.access_token && data?.refresh_token) {
        localStorage.setItem('bomapos_token', data.access_token);
        localStorage.setItem('bomapos_refresh_token', data.refresh_token);
        return true;
      }
      return false;
    } catch (e) {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function request(endpoint, options = {}, isRetry = false) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeader(),
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, { ...options, headers });

    // Retry once on 401 via refresh token rotation (except on auth endpoints themselves)
    if (
      res.status === 401 &&
      !isRetry &&
      !endpoint.startsWith('/api/auth/login') &&
      !endpoint.startsWith('/api/auth/refresh')
    ) {
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        return request(endpoint, options, true);
      }
    }

    const data = await res.json().catch(() => null);

    if (!res.ok) {
      const errorMsg = data?.detail || `HTTP Error ${res.status}`;
      const err = new Error(errorMsg);
      err.status = res.status;
      throw err;
    }
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

export const api = {
  // Auth
  login: (tenantSlug, username, password) =>
    request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ tenant_slug: tenantSlug, username, password }),
    }),

  logout: (refreshToken) =>
    request('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
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
    // Strip any legacy cashier_id from payload before sending or queuing
    const cleanPayload = { ...payload };
    delete cleanPayload.cashier_id;

    // 1. If currently offline (or in simulated offline mode), intercept immediately
    if (!offlineQueue.effectiveOnline) {
      console.log('[API] Client is offline. Intercepting order creation to offline queue.');
      return offlineQueue.enqueueOrder(cleanPayload, itemsDetail);
    }

    // 2. Attempt online network creation
    try {
      return await request('/api/orders', {
        method: 'POST',
        body: JSON.stringify(cleanPayload),
      });
    } catch (err) {
      // 3. Critical: If network fails OR token expired (401 after refresh failure),
      // NEVER block or discard the order — save to offline queue so it flushes after re-auth!
      const isNetworkOrAuthIssue =
        !navigator.onLine ||
        err.status === 401 ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('network');

      if (isNetworkOrAuthIssue) {
        console.warn('[API] Network or auth failure while posting order. Saving to offline queue.');
        return offlineQueue.enqueueOrder(cleanPayload, itemsDetail);
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
