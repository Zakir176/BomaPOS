<template>
  <aside class="bento-sidebar">
    <!-- Brand Emblem at Top -->
    <div class="sidebar-brand">
      <div class="emblem-shield">
        <UtensilsCrossed :size="20" :stroke-width="2.4" />
      </div>
      <div class="brand-text">
        <span class="brand-name">BomaPOS</span>
        <span class="brand-sub">Lusaka #01</span>
      </div>
    </div>

    <!-- Navigation Item Capsule Tabs -->
    <nav class="sidebar-nav">
      <!-- 1. Cashier Register (All roles) -->
      <button
        class="nav-tab-btn"
        :class="{ active: currentView === 'pos' }"
        @click="$emit('change-view', 'pos')"
        title="Cashier POS Register"
      >
        <div class="tab-icon-box">
          <Receipt :size="18" :stroke-width="2.2" />
        </div>
        <div class="tab-labels">
          <span class="tab-title">Register</span>
          <span class="tab-subtitle">Order & Cart</span>
        </div>
      </button>

      <!-- 2. Owner Telemetry / Dashboard (Visible to all or owner badge) -->
      <button
        v-if="authState.isOwner"
        class="nav-tab-btn"
        :class="{ active: currentView === 'dashboard' }"
        @click="$emit('change-view', 'dashboard')"
        title="Owner Telemetry & Analytics"
      >
        <div class="tab-icon-box">
          <BarChart3 :size="18" :stroke-width="2.2" />
        </div>
        <div class="tab-labels">
          <span class="tab-title">Analytics</span>
          <span class="tab-subtitle">Revenue & MoMo</span>
        </div>
      </button>

      <!-- 3. Drink Inventory Telemetry -->
      <button
        class="nav-tab-btn"
        :class="{ active: currentView === 'inventory' }"
        @click="handleInventoryClick"
        title="Beverage Crate Inventory"
      >
        <div class="tab-icon-box">
          <Boxes :size="18" :stroke-width="2.2" />
        </div>
        <div class="tab-labels">
          <span class="tab-title">Inventory</span>
          <span class="tab-subtitle">Drink Crates</span>
        </div>
      </button>
    </nav>

    <!-- Bottom Operator Capsule & Lock Out -->
    <div class="sidebar-footer">
      <div class="operator-capsule card-bento">
        <div class="user-avatar-circle" :class="authState.user?.role">
          {{ authState.user?.username ? authState.user.username.charAt(0).toUpperCase() : 'U' }}
        </div>
        <div class="user-meta">
          <span class="user-display-name">{{ authState.user?.username }}</span>
          <span class="user-role-sub">{{ authState.user?.role === 'owner' ? 'Administrator' : 'Floor Register' }}</span>
        </div>
      </div>

      <button class="btn-pill-outline lock-shift-btn" @click="handleLogout" title="Lock Register & End Shift">
        <Lock :size="14" :stroke-width="2.2" />
        <span>Lock Terminal</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import {
  UtensilsCrossed,
  Receipt,
  BarChart3,
  Boxes,
  Lock,
} from 'lucide-vue-next';
import { authState } from '../stores/auth.js';

const props = defineProps({
  currentView: {
    type: String,
    required: true,
  },
});

const emit = defineEmits(['change-view']);

const handleInventoryClick = () => {
  if (authState.isOwner) {
    emit('change-view', 'dashboard');
  } else {
    emit('change-view', 'pos');
  }
};

const handleLogout = () => {
  authState.logout();
};
</script>

<style scoped>
.bento-sidebar {
  width: 200px;
  min-width: 200px;
  background-color: var(--color-surface);
  border-right: 1px solid var(--color-border-card);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 18px 12px;
  height: 100vh;
  z-index: 50;
  box-shadow: 2px 0 12px rgba(12, 26, 18, 0.03);
}

/* Brand */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 18px;
  border-bottom: 1px solid var(--color-border-card);
}

.emblem-shield {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(20, 77, 47, 0.2);
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-on-surface);
  letter-spacing: -0.02em;
  line-height: 1.1;
}

.brand-sub {
  font-size: 10px;
  color: var(--color-on-surface-variant);
  font-weight: 500;
  margin-top: 2px;
}

/* Nav Items */
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
  flex: 1;
}

.nav-tab-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-pill);
  background-color: transparent;
  border: 1px solid transparent;
  color: var(--color-on-surface-variant);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  width: 100%;
}

.nav-tab-btn:hover {
  background-color: var(--color-surface-dim);
  color: var(--color-on-surface);
}

.nav-tab-btn.active {
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  box-shadow: 0 4px 12px rgba(20, 77, 47, 0.25);
}

.tab-icon-box {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-surface-dim);
  color: var(--color-on-surface);
  flex-shrink: 0;
}

.nav-tab-btn.active .tab-icon-box {
  background-color: rgba(255, 255, 255, 0.2);
  color: #FFFFFF;
}

.tab-labels {
  display: flex;
  flex-direction: column;
}

.tab-title {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.1;
}

.tab-subtitle {
  font-size: 10px;
  color: var(--color-on-surface-muted);
  margin-top: 2px;
}

.nav-tab-btn.active .tab-subtitle {
  color: rgba(255, 255, 255, 0.7);
}

/* Bottom Footer */
.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border-card);
}

.operator-capsule {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background-color: var(--color-surface-dim);
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
  flex-shrink: 0;
}

.user-avatar-circle.owner {
  background-color: var(--color-tertiary);
}

.user-avatar-circle.cashier {
  background-color: var(--color-primary);
}

.user-meta {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.user-display-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-on-surface);
  line-height: 1.1;
}

.user-role-sub {
  font-size: 9px;
  color: var(--color-on-surface-muted);
}

.lock-shift-btn {
  width: 100%;
  padding: 8px;
  font-size: 12px;
  justify-content: center;
}
</style>
