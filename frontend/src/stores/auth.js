import { reactive, computed } from 'vue';
import { api } from '../services/api.js';
import { offlineQueue } from './offlineQueue.js';

// Load stored session if any
const storedUser = localStorage.getItem('bomapos_user');
const initialUser = storedUser ? JSON.parse(storedUser) : null;

export const authState = reactive({
  user: initialUser,
  isAuthenticated: computed(() => !!authState.user),
  isOwner: computed(() => authState.user?.role === 'owner'),
  isCashier: computed(() => authState.user?.role === 'cashier'),

  login(userData, accessToken, refreshToken = null) {
    authState.user = userData;
    localStorage.setItem('bomapos_user', JSON.stringify(userData));
    localStorage.setItem('bomapos_token', accessToken);
    if (refreshToken) {
      localStorage.setItem('bomapos_refresh_token', refreshToken);
    }
    // Critical: If offline orders were waiting for re-authentication, flush them immediately
    if (offlineQueue.hasPendingOrders && offlineQueue.effectiveOnline) {
      setTimeout(() => {
        offlineQueue.syncQueue();
      }, 150);
    }
  },

  async logout() {
    const refreshToken = localStorage.getItem('bomapos_refresh_token');
    try {
      await api.logout(refreshToken);
    } catch (e) {
      // Ignore network/401 errors during local logout cleanup
    }
    authState.clearSession();
  },

  clearSession() {
    authState.user = null;
    localStorage.removeItem('bomapos_user');
    localStorage.removeItem('bomapos_token');
    localStorage.removeItem('bomapos_refresh_token');
  },
});
