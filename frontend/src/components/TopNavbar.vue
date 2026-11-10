<template>
  <header class="bento-navbar">
    <div class="nav-left">
      <!-- Brand & Central Emblem -->
      <div class="brand-capsule">
        <div class="emblem-shield">
          <UtensilsCrossed :size="18" :stroke-width="2.4" />
        </div>
        <div class="brand-text">
          <div class="brand-line">
            <span class="brand-name">BomaPOS</span>
            <span class="badge-pill badge-pill-mint version-pill">Bento PWA</span>
          </div>
          <span class="brand-sub">Lusaka Terminal #01 • Aunt's Restaurant</span>
        </div>
      </div>

      <!-- Online/Offline Status Indicator -->
      <div
        class="network-chip"
        :class="{
          'is-online': offlineQueue.effectiveOnline && !offlineQueue.isSyncing,
          'is-offline': !offlineQueue.effectiveOnline,
          'is-syncing': offlineQueue.isSyncing,
        }"
      >
        <span class="pulse-indicator"></span>
        <span class="network-label font-data-mono">
          <template v-if="offlineQueue.isSyncing">
            Syncing ({{ offlineQueue.queuedCount }} Queue)...
          </template>
          <template v-else-if="!offlineQueue.effectiveOnline">
            Offline (Queue Active: {{ offlineQueue.queuedCount }})
          </template>
          <template v-else>
            Online • 127.0.0.1:8000
          </template>
        </span>
      </div>

      <!-- Flush Queue Button (Visible when queue has items) -->
      <button
        v-if="offlineQueue.queuedCount > 0 && offlineQueue.effectiveOnline"
        class="btn-pill-primary flush-queue-btn"
        :disabled="offlineQueue.isSyncing"
        @click="handleManualSync"
        title="Synchronize offline stored orders with backend database"
      >
        <RefreshCw :size="12" :stroke-width="2.4" :class="{ 'spin-anim': offlineQueue.isSyncing }" />
        <span>Sync Queue ({{ offlineQueue.queuedCount }})</span>
      </button>

      <!-- Developer / Tester Offline Toggle Button -->
      <button
        class="btn-pill-outline sim-offline-btn"
        :class="{ 'sim-active': offlineQueue.isSimulatedOffline }"
        @click="offlineQueue.toggleSimulatedOffline()"
        :title="offlineQueue.isSimulatedOffline ? 'Resume Live Network Connection' : 'Simulate WiFi/Internet Outage (Offline Queue Demo)'"
      >
        <WifiOff v-if="offlineQueue.isSimulatedOffline" :size="13" :stroke-width="2.4" />
        <Wifi v-else :size="13" :stroke-width="2.2" />
        <span>{{ offlineQueue.isSimulatedOffline ? 'Restore Network' : 'Test Offline Mode' }}</span>
      </button>

      <!-- Live Clock Chip -->
      <div class="clock-chip">
        <Clock :size="13" :stroke-width="2.2" />
        <span class="clock-text font-data-mono">{{ currentTime }}</span>
      </div>
    </div>

    <!-- Navigation Right Controls -->
    <div class="nav-right" v-if="authState.isAuthenticated">
      <!-- View Switcher Toggle -->
      <div class="view-pill-toggle">
        <button
          class="toggle-segment"
          :class="{ active: currentView === 'pos' }"
          @click="$emit('change-view', 'pos')"
        >
          <Receipt :size="14" :stroke-width="2.2" />
          <span>Cashier Register</span>
        </button>

        <button
          v-if="authState.isOwner"
          class="toggle-segment"
          :class="{ active: currentView === 'dashboard' }"
          @click="$emit('change-view', 'dashboard')"
        >
          <BarChart3 :size="14" :stroke-width="2.2" />
          <span>Owner Dashboard</span>
        </button>

        <div
          v-else
          class="toggle-segment locked"
          title="Switch to Aunt account to access Executive Dashboard"
        >
          <Lock :size="12" :stroke-width="2" />
          <span>Owner Only</span>
        </div>
      </div>

      <!-- User Profile & Role Badge -->
      <div class="user-capsule">
        <div class="user-avatar-circle" :class="authState.user?.role">
          {{ authState.user?.username ? authState.user.username.charAt(0).toUpperCase() : 'U' }}
        </div>
        <div class="user-meta">
          <span class="user-display-name">{{ authState.user?.username }}</span>
          <span
            class="badge-pill role-pill"
            :class="authState.isOwner ? 'badge-pill-ochre' : 'badge-pill-mint'"
          >
            <ShieldCheck v-if="authState.isOwner" :size="10" :stroke-width="2.5" />
            <Receipt v-else :size="10" :stroke-width="2.5" />
            {{ authState.isOwner ? 'Owner' : 'Cashier' }}
          </span>
        </div>
      </div>

      <!-- Lock Shift Button -->
      <button class="btn-pill-outline lock-btn" @click="handleLogout" title="Lock Register & End Shift">
        <Lock :size="13" :stroke-width="2.2" />
        <span>Lock Shift</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import {
  UtensilsCrossed,
  Receipt,
  BarChart3,
  Lock,
  Clock,
  ShieldCheck,
  Wifi,
  WifiOff,
  RefreshCw,
} from 'lucide-vue-next';
import { authState } from '../stores/auth.js';
import { offlineQueue } from '../stores/offlineQueue.js';

defineProps({
  currentView: {
    type: String,
    required: true,
  },
});

defineEmits(['change-view']);

const currentTime = ref('');
let clockTimer = null;

const updateClock = () => {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  currentTime.value = `${timeStr} CAT`;
};

const handleManualSync = async () => {
  await offlineQueue.syncQueue();
};

onMounted(() => {
  updateClock();
  clockTimer = setInterval(updateClock, 1000);
});

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer);
});

const handleLogout = () => {
  authState.logout();
};
</script>

<style scoped>
.bento-navbar {
  height: 64px;
  background-color: var(--color-surface);
  border-bottom: 1px solid var(--color-border-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  position: relative;
  z-index: 40;
  box-shadow: 0 1px 4px rgba(12, 26, 18, 0.03);
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-capsule {
  display: flex;
  align-items: center;
  gap: 10px;
}

.emblem-shield {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(20, 77, 47, 0.2);
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.brand-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-on-surface);
  letter-spacing: -0.02em;
}

.version-pill {
  font-size: 9px;
  padding: 1px 7px;
}

.brand-sub {
  font-size: 10.5px;
  color: var(--color-on-surface-variant);
  font-weight: 500;
}

/* Network Chip States */
.network-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  font-size: 11px;
  color: var(--color-on-surface-variant);
  transition: all 0.2s ease;
}

.network-chip.is-online {
  border-color: rgba(52, 168, 100, 0.3);
  background-color: rgba(52, 168, 100, 0.06);
}

.network-chip.is-online .pulse-indicator {
  background-color: var(--color-primary-accent);
  box-shadow: 0 0 0 3px rgba(52, 168, 100, 0.25);
}

.network-chip.is-offline {
  border-color: rgba(180, 120, 24, 0.4);
  background-color: var(--color-tertiary-container);
  color: var(--color-on-tertiary-container);
  font-weight: 700;
}

.network-chip.is-offline .pulse-indicator {
  background-color: var(--color-tertiary-accent);
  box-shadow: 0 0 0 3px rgba(180, 120, 24, 0.3);
  animation: pulseOffline 1s infinite alternate;
}

.network-chip.is-syncing .pulse-indicator {
  background-color: #3B82F6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
}

.pulse-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  animation: pulseBeacon 2s infinite ease-in-out;
}

@keyframes pulseBeacon {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.25); opacity: 0.75; }
}

@keyframes pulseOffline {
  0% { transform: scale(0.9); opacity: 0.7; }
  100% { transform: scale(1.3); opacity: 1; }
}

.flush-queue-btn {
  padding: 4px 10px;
  font-size: 11px;
  gap: 5px;
  background-color: var(--color-tertiary);
  border-color: var(--color-tertiary);
}

.flush-queue-btn:hover:not(:disabled) {
  background-color: var(--color-tertiary-accent);
}

.sim-offline-btn {
  padding: 4px 10px;
  font-size: 11px;
  gap: 5px;
}

.sim-offline-btn.sim-active {
  background-color: var(--color-error-container);
  border-color: rgba(196, 50, 66, 0.4);
  color: var(--color-error);
  font-weight: 700;
}

.spin-anim {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.clock-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-on-surface-variant);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.view-pill-toggle {
  display: flex;
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  padding: 3px;
  border-radius: var(--radius-pill);
  gap: 2px;
}

.toggle-segment {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-on-surface-variant);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.toggle-segment:hover:not(.active):not(.locked) {
  color: var(--color-on-surface);
  background-color: rgba(0, 0, 0, 0.04);
}

.toggle-segment.active {
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  box-shadow: 0 2px 6px rgba(20, 77, 47, 0.2);
}

.toggle-segment.locked {
  cursor: not-allowed;
  opacity: 0.55;
  color: var(--color-on-surface-muted);
}

.user-capsule {
  display: flex;
  align-items: center;
  gap: 8px;
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  padding: 4px 12px 4px 5px;
  border-radius: var(--radius-pill);
}

.user-avatar-circle {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #FFFFFF;
}

.user-avatar-circle.owner {
  background-color: var(--color-tertiary);
}

.user-avatar-circle.cashier {
  background-color: var(--color-primary);
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-display-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.role-pill {
  font-size: 9px;
  padding: 1px 7px;
  text-transform: uppercase;
}

.lock-btn {
  padding: 6px 14px;
  font-size: 12px;
}

@media (max-width: 1024px) {
  .clock-chip {
    display: none;
  }
}

@media (max-width: 850px) {
  .sim-offline-btn {
    display: none;
  }
}
</style>
