<template>
  <div id="bomapos-app">
    <!-- If not authenticated: full-screen login -->
    <LoginView v-if="!authState.isAuthenticated" />

    <!-- If authenticated: Bento Top Header + Main Content Area -->
    <div v-else class="app-shell-layout">
      <!-- Top Navigation Bar -->
      <TopNavbar
        :current-view="currentView"
        @change-view="setView"
      />

      <!-- Main Content Region -->
      <main class="app-main-content">
        <!-- 1. Cashier POS Split-Screen Bento (70% / 30%) -->
        <CashierPosView
          v-if="currentView === 'pos'"
        />

        <!-- 2. Owner Bento Executive Dashboard -->
        <OwnerDashboardView
          v-else-if="currentView === 'dashboard' && authState.isOwner"
          @change-view="setView"
        />
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';
import { authState } from './stores/auth.js';
import TopNavbar from './components/TopNavbar.vue';
import LoginView from './components/LoginView.vue';
import CashierPosView from './components/CashierPosView.vue';
import OwnerDashboardView from './components/OwnerDashboardView.vue';

const currentView = ref('pos'); // 'pos' or 'dashboard'

const setView = (view) => {
  if (view === 'dashboard' && !authState.isOwner) {
    currentView.value = 'pos';
    return;
  }
  currentView.value = view;
};

// Reset to POS if user logs out or switches accounts
watch(
  () => authState.user,
  (newUser) => {
    if (!newUser || newUser.role !== 'owner') {
      currentView.value = 'pos';
    }
  }
);
</script>

<style>
#bomapos-app {
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  display: flex;
  background-color: var(--color-background);
}

.app-shell-layout {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.app-main-content {
  flex: 1;
  height: calc(100vh - 64px);
  overflow: hidden;
  background-color: var(--color-background);
}
</style>
