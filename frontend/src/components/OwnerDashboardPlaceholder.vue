<template>
  <div class="dashboard-placeholder">
    <div class="placeholder-card">
      <div class="icon">📊</div>
      <h2>Owner Dashboard</h2>
      <p class="desc">
        Welcome, <strong>{{ authState.user?.username }}</strong>. Real-time daily revenue, Lenco settlement tracking, drink inventory management, and calendar analytics will be integrated here in the next step.
      </p>

      <div class="actions">
        <button class="back-btn" @click="$emit('change-view', 'pos')">
          ← Switch Back to Cashier POS
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { authState } from '../stores/auth.js';

defineEmits(['change-view']);
</script>

<style scoped>
.dashboard-placeholder {
  min-height: calc(100vh - 64px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--color-bg);
}

.placeholder-card {
  max-width: 500px;
  background: white;
  border-radius: 16px;
  padding: 36px;
  text-align: center;
  box-shadow: var(--shadow-md);
  border: 1px solid var(--color-border);
}

.icon {
  font-size: 48px;
  margin-bottom: 16px;
}

h2 {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-primary);
  margin-bottom: 12px;
}

.desc {
  font-size: 14px;
  color: var(--color-text-muted);
  line-height: 1.6;
  margin-bottom: 24px;
}

.back-btn {
  padding: 12px 24px;
  background: var(--color-primary);
  color: white;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
}
</style>
