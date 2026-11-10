<template>
  <div class="login-bento-viewport bg-hatch-diagonal">
    <div class="login-bento-card card-bento animate-bento-in">
      <!-- Inverted Hero Header (#0B2416) -->
      <div class="login-hero-header card-bento-hero bg-topo-dark">
        <div class="hero-emblem-circle">
          <UtensilsCrossed :size="24" :stroke-width="2.4" />
        </div>
        <h1 class="hero-title">BomaPOS</h1>
        <p class="hero-sub">Zambian Restaurant POS & MoMo Engine</p>
      </div>

      <!-- Quick Shift Operator Selector -->
      <div class="shift-operator-section">
        <span class="section-label">Select Operator Shift:</span>
        <div class="operator-capsule-row">
          <button
            type="button"
            class="operator-capsule"
            :class="{ active: username === 'cashier1' }"
            @click="selectQuick('cashier1', 'cashier123')"
          >
            <span class="operator-dot cashier"></span>
            <div class="operator-meta">
              <span class="op-name">cashier1</span>
              <span class="op-role">Floor Register</span>
            </div>
          </button>

          <button
            type="button"
            class="operator-capsule"
            :class="{ active: username === 'aunt' }"
            @click="selectQuick('aunt', 'owner123')"
          >
            <span class="operator-dot owner"></span>
            <div class="operator-meta">
              <span class="op-name">aunt</span>
              <span class="op-role">Owner / Admin</span>
            </div>
          </button>
        </div>
      </div>

      <!-- Login Form -->
      <form @submit.prevent="handleLogin" class="bento-form">
        <div class="input-field-group">
          <label>Username</label>
          <input
            v-model="username"
            type="text"
            required
            class="bento-text-input"
            placeholder="Operator username"
          />
        </div>

        <div class="input-field-group">
          <label>PIN / Password</label>
          <input
            v-model="password"
            type="password"
            required
            class="bento-text-input font-data-mono"
            placeholder="Operator password"
          />
        </div>

        <div v-if="errorMessage" class="badge-pill badge-pill-red form-error">
          <AlertCircle :size="13" :stroke-width="2.5" />
          <span>{{ errorMessage }}</span>
        </div>

        <button type="submit" class="btn-pill-primary submit-btn" :disabled="isLoading">
          <span v-if="isLoading">Authorizing...</span>
          <span v-else>Unlock Register & Open Shift</span>
          <ArrowRight v-if="!isLoading" :size="15" :stroke-width="2.2" />
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import {
  UtensilsCrossed,
  ShieldCheck,
  AlertCircle,
  ArrowRight,
} from 'lucide-vue-next';
import { api } from '../services/api.js';
import { authState } from '../stores/auth.js';

const username = ref('cashier1');
const password = ref('cashier123');
const isLoading = ref(false);
const errorMessage = ref('');

const selectQuick = (user, pass) => {
  username.value = user;
  password.value = pass;
  errorMessage.value = '';
};

const handleLogin = async () => {
  isLoading.value = true;
  errorMessage.value = '';

  try {
    const res = await api.login(username.value, password.value);
    authState.login({ id: res.id, username: res.username, role: res.role }, res.token);
  } catch (err) {
    errorMessage.value = err.message || 'Login failed. Please verify credentials.';
  } finally {
    isLoading.value = false;
  }
};
</script>

<style scoped>
.login-bento-viewport {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-bento-card {
  width: 100%;
  max-width: 440px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.login-hero-header {
  padding: 30px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  border-radius: var(--radius-bento) var(--radius-bento) 0 0;
}

.hero-emblem-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background-color: var(--color-primary-accent);
  color: var(--color-on-primary-container);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
  box-shadow: 0 4px 14px rgba(52, 168, 100, 0.4);
}

.hero-title {
  font-size: 24px;
  font-weight: 700;
  color: #FFFFFF;
  letter-spacing: -0.02em;
}

.hero-sub {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  margin-top: 2px;
}

.fiscal-tag {
  font-size: 10px;
  margin-top: 10px;
}

.shift-operator-section {
  padding: 16px 20px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-on-surface-variant);
  text-transform: uppercase;
}

.operator-capsule-row {
  display: flex;
  gap: 10px;
}

.operator-capsule {
  flex: 1;
  padding: 10px 14px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.operator-capsule.active {
  background-color: var(--color-surface);
  border-color: var(--color-primary);
  box-shadow: var(--shadow-bento);
}

.operator-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.operator-dot.cashier {
  background-color: var(--color-primary);
}

.operator-dot.owner {
  background-color: var(--color-tertiary);
}

.operator-meta {
  display: flex;
  flex-direction: column;
}

.op-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.op-role {
  font-size: 10px;
  color: var(--color-on-surface-muted);
}

.bento-form {
  padding: 16px 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.input-field-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.input-field-group label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-on-surface-variant);
}

.bento-text-input {
  height: 44px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  padding: 0 16px;
  font-size: 14px;
  color: var(--color-on-surface);
  outline: none;
  transition: all 0.15s ease;
}

.bento-text-input:focus {
  background-color: var(--color-surface);
  border-color: var(--color-primary-accent);
  box-shadow: 0 0 0 3px rgba(52, 168, 100, 0.15);
}

.form-error {
  width: 100%;
  justify-content: center;
}

.submit-btn {
  height: 48px;
  margin-top: 6px;
  font-size: 14px;
}
</style>
