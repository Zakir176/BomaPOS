import { reactive, computed } from 'vue';
import { api } from '../services/api.js';

// Load stored session if any
const storedUser = localStorage.getItem('bomapos_user');
const initialUser = storedUser ? JSON.parse(storedUser) : null;

export const authState = reactive({
  user: initialUser,
  isAuthenticated: computed(() => !!authState.user),
  isOwner: computed(() => authState.user?.role === 'owner'),
  isCashier: computed(() => authState.user?.role === 'cashier'),

  login(userData, token) {
    authState.user = userData;
    localStorage.setItem('bomapos_user', JSON.stringify(userData));
    localStorage.setItem('bomapos_token', token);
  },

  logout() {
    authState.user = null;
    localStorage.removeItem('bomapos_user');
    localStorage.removeItem('bomapos_token');
  },
});
