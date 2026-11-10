<template>
  <div class="owner-bento-viewport bg-hatch-diagonal">
    <div class="owner-bento-container animate-bento-in">
      <!-- ======================================================== -->
      <!-- TOP ROW: INVERTED HERO BENTO CARD (#0B2416)              -->
      <!-- ======================================================== -->
      <section class="hero-bento-card card-bento-hero bg-topo-dark">
        <div class="hero-card-header">
          <div class="hero-brand-group">
            <div class="hero-emblem-badge">
              <Crown :size="20" :stroke-width="2.4" />
            </div>
            <div>
              <div class="hero-title-row">
                <h2 class="hero-title">Executive Revenue & Settlement Telemetry</h2>
                <span class="badge-pill badge-pill-mint">Live Fiscal Engine</span>
              </div>
              <p class="hero-caption">
                Lusaka Branch #01 • Real-time ZRA audit compliance & automated Lenco settlement
              </p>
            </div>
          </div>

          <div class="hero-header-actions">
            <!-- Last Sync readout -->
            <div class="sync-time-chip font-data-mono">
              <span class="sync-dot"></span>
              <span>Updated {{ lastUpdatedTime || 'Just now' }}</span>
            </div>

            <!-- Manual Refresh Action -->
            <button
              class="btn-pill-outline hero-refresh-btn"
              :disabled="isLoadingSummary"
              @click="loadAllDashboardData"
              title="Refresh Analytics from Backend"
            >
              <RefreshCw
                :size="14"
                :stroke-width="2.2"
                :class="{ 'spin-anim': isLoadingSummary }"
              />
              <span>{{ isLoadingSummary ? 'Syncing...' : 'Refresh' }}</span>
            </button>
          </div>
        </div>

        <!-- Metric KPI Bento Cluster -->
        <div class="hero-metrics-grid">
          <!-- 1. Today's Total Revenue -->
          <div class="metric-card">
            <div class="metric-top">
              <span class="metric-label">TODAY'S TOTAL REVENUE</span>
              <div class="metric-icon-bubble">
                <TrendingUp :size="16" :stroke-width="2.4" />
              </div>
            </div>
            <div class="metric-value-row">
              <span class="currency-prefix">ZMW</span>
              <span class="metric-num font-data-mono">
                {{ formatMoney(animatedMetrics.todayTotal) }}
              </span>
            </div>
            <div class="metric-footer">
              <span class="badge-pill badge-pill-mint">
                <CheckCircle2 :size="11" :stroke-width="2.2" />
                {{ summaryData.today_orders_count }} Paid Orders Today
              </span>
            </div>
          </div>

          <!-- 2. Today's Cash Register Total -->
          <div class="metric-card">
            <div class="metric-top">
              <span class="metric-label">DAILY CASH DRAWER</span>
              <div class="metric-icon-bubble cash">
                <Banknote :size="16" :stroke-width="2.4" />
              </div>
            </div>
            <div class="metric-value-row">
              <span class="currency-prefix">ZMW</span>
              <span class="metric-num font-data-mono">
                {{ formatMoney(animatedMetrics.todayCash) }}
              </span>
            </div>
            <div class="metric-footer">
              <span class="metric-sub-detail">Physical currency reconciliation ready</span>
            </div>
          </div>

          <!-- 3. Lenco Settlement Account Balance -->
          <div class="metric-card lenco-accent">
            <div class="metric-top">
              <span class="metric-label">LENCO SETTLEMENT BALANCE</span>
              <div class="metric-icon-bubble lenco">
                <Zap :size="16" :stroke-width="2.4" />
              </div>
            </div>
            <div class="metric-value-row">
              <span class="currency-prefix text-mint">ZMW</span>
              <span class="metric-num font-data-mono text-mint">
                {{ formatMoney(animatedMetrics.settlementBalance) }}
              </span>
            </div>
            <div class="metric-footer">
              <span class="badge-pill badge-pill-charcoal font-data-mono">
                Sub-Account: LENCO-ZMW-8921
              </span>
            </div>
          </div>
        </div>

        <!-- Offline Queue Status Banner inside Hero -->
        <div v-if="offlineQueue.queuedCount > 0" class="hero-offline-queue-strip animate-bento-in">
          <div class="queue-strip-info">
            <AlertCircle :size="16" class="text-ochre" />
            <span>
              <strong>{{ offlineQueue.queuedCount }} Offline Order{{ offlineQueue.queuedCount > 1 ? 's' : '' }}</strong>
              stored locally during network outage.
            </span>
          </div>
          <button
            v-if="offlineQueue.effectiveOnline"
            class="btn-pill-primary sync-strip-btn"
            :disabled="offlineQueue.isSyncing"
            @click="offlineQueue.syncQueue()"
          >
            <RefreshCw :size="12" :stroke-width="2.4" :class="{ 'spin-anim': offlineQueue.isSyncing }" />
            <span>{{ offlineQueue.isSyncing ? 'Flushing...' : 'Flush Queue to DB' }}</span>
          </button>
          <span v-else class="badge-pill badge-pill-ochre font-data-mono">
            Waiting for Network Link
          </span>
        </div>
      </section>

      <!-- ======================================================== -->
      <!-- SECONDARY BENTO GRID (BOTTOM ROWS)                       -->
      <!-- ======================================================== -->
      <div class="secondary-bento-grid">
        <!-- ====================================================== -->
        <!-- MODULE 1: DRINK INVENTORY WATCHER                      -->
        <!-- ====================================================== -->
        <section class="card-bento inventory-watcher-card">
          <div class="module-card-header">
            <div class="module-title-group">
              <div class="module-icon-shield">
                <Boxes :size="18" :stroke-width="2.4" />
              </div>
              <div>
                <h3 class="module-title">Beverage & Crate Inventory Watcher</h3>
                <p class="module-caption">
                  Real-time stock depletion tracker against safety thresholds
                </p>
              </div>
            </div>

            <!-- Restock Quick Action -->
            <button
              class="btn-pill-primary restock-quick-btn"
              @click="openRestockModal()"
              title="Quick Restock Drinks"
            >
              <Plus :size="14" :stroke-width="2.5" />
              <span>Restock Crates</span>
            </button>
          </div>

          <!-- Low Stock Alert Banner (Visible if any drink is low stock) -->
          <div v-if="lowStockItems.length > 0" class="low-stock-alert-banner">
            <AlertTriangle class="alert-icon" :size="18" :stroke-width="2.4" />
            <div class="alert-text">
              <strong>{{ lowStockItems.length }} Beverage{{ lowStockItems.length > 1 ? 's' : '' }} Below Safety Threshold</strong>
              <span>Restock required to avoid POS order rejections on high-demand drinks.</span>
            </div>
          </div>

          <!-- Drinks Table / List -->
          <div class="inventory-table-container">
            <div v-if="isLoadingDrinks" class="loading-state">
              <Loader2 class="spin-anim" :size="22" :stroke-width="2.2" />
              <span>Fetching live beverage crates...</span>
            </div>

            <table v-else class="bento-table">
              <thead>
                <tr>
                  <th>Beverage Item</th>
                  <th>Unit Price</th>
                  <th>Stock In Crate</th>
                  <th>Safety Threshold</th>
                  <th>Status</th>
                  <th class="text-right">Quick Restock</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="drink in drinkList"
                  :key="drink.id"
                  :class="{ 'row-warning': drink.is_low_stock || drink.stock_quantity <= drink.low_stock_threshold }"
                >
                  <!-- Drink Name -->
                  <td>
                    <div class="drink-item-cell">
                      <div class="drink-icon-box">
                        <Wine :size="15" :stroke-width="2.2" />
                      </div>
                      <span class="drink-name">{{ drink.name }}</span>
                    </div>
                  </td>

                  <!-- Price -->
                  <td>
                    <span class="font-data-mono table-price">
                      K{{ drink.price_zmw.toFixed(2) }}
                    </span>
                  </td>

                  <!-- Current Stock with progress bar -->
                  <td>
                    <div class="stock-progress-cell">
                      <span class="font-data-mono stock-number font-bold">
                        {{ drink.stock_quantity }}
                      </span>
                      <div class="mini-progress-track">
                        <div
                          class="mini-progress-fill"
                          :class="getProgressFillClass(drink)"
                          :style="{ width: getStockPercentage(drink) + '%' }"
                        ></div>
                      </div>
                    </div>
                  </td>

                  <!-- Threshold -->
                  <td>
                    <span class="font-data-mono text-muted">
                      {{ drink.low_stock_threshold }} units
                    </span>
                  </td>

                  <!-- Status Pill -->
                  <td>
                    <span
                      class="badge-pill"
                      :class="getDrinkBadgeClass(drink)"
                    >
                      {{ getDrinkStatusLabel(drink) }}
                    </span>
                  </td>

                  <!-- Inline Quick Add Buttons (+6, +24) -->
                  <td class="text-right">
                    <div class="inline-restock-actions">
                      <button
                        class="btn-pill-outline btn-micro"
                        :disabled="isUpdatingStock"
                        @click="quickIncrementStock(drink, 6)"
                        title="Add 6 units"
                      >
                        +6
                      </button>
                      <button
                        class="btn-pill-outline btn-micro"
                        :disabled="isUpdatingStock"
                        @click="quickIncrementStock(drink, 24)"
                        title="Add 1 Crate (24 bottles)"
                      >
                        +1 Crate
                      </button>
                      <button
                        class="btn-pill-outline btn-micro edit-btn"
                        @click="openRestockModal(drink)"
                        title="Edit Threshold / Stock"
                      >
                        <Edit3 :size="12" :stroke-width="2.2" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- ====================================================== -->
        <!-- MODULE 2: REVENUE & MEALS CALENDAR HISTORY             -->
        <!-- ====================================================== -->
        <section class="card-bento calendar-history-card">
          <div class="module-card-header">
            <div class="module-title-group">
              <div class="module-icon-shield calendar">
                <Calendar :size="18" :stroke-width="2.4" />
              </div>
              <div>
                <h3 class="module-title">Revenue & Meals Daily History</h3>
                <p class="module-caption">
                  Aggregated performance breakdown per operational date
                </p>
              </div>
            </div>

            <!-- Month Filter Pills -->
            <div class="month-pill-filter">
              <span class="filter-label">Filter:</span>
              <button
                class="filter-pill"
                :class="{ active: selectedMonthFilter === null }"
                @click="filterMonth(null)"
              >
                All
              </button>
              <button
                class="filter-pill"
                :class="{ active: selectedMonthFilter === currentMonthNumber }"
                @click="filterMonth(currentMonthNumber)"
              >
                Current Month
              </button>
            </div>
          </div>

          <!-- Calendar Performance Table -->
          <div class="calendar-table-container">
            <div v-if="isLoadingCalendar" class="loading-state">
              <Loader2 class="spin-anim" :size="22" :stroke-width="2.2" />
              <span>Compiling historical ledger...</span>
            </div>

            <div v-else-if="calendarData.length === 0" class="empty-state">
              <Calendar :size="32" :stroke-width="1.8" />
              <h4>No Closed Shifts Found</h4>
              <p>Place orders in Cashier Register to populate analytics.</p>
            </div>

            <table v-else class="bento-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Total Revenue</th>
                  <th>Orders</th>
                  <th>Meals Sold</th>
                  <th>Avg Ticket</th>
                  <th class="text-right">Relative Volume</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="day in sortedCalendarData"
                  :key="day.date"
                  :class="{ 'row-today': isToday(day.date) }"
                >
                  <!-- Formatted Date -->
                  <td>
                    <div class="date-cell">
                      <span class="date-text font-data-mono font-bold">{{ day.date }}</span>
                      <span v-if="isToday(day.date)" class="badge-pill badge-pill-mint today-pill">Today</span>
                    </div>
                  </td>

                  <!-- Total Revenue -->
                  <td>
                    <span class="font-data-mono revenue-text font-bold">
                      ZMW {{ day.total_revenue_zmw.toFixed(2) }}
                    </span>
                  </td>

                  <!-- Orders Count -->
                  <td>
                    <span class="font-data-mono count-text">
                      {{ day.total_orders_count }}
                    </span>
                  </td>

                  <!-- Meals Sold -->
                  <td>
                    <div class="meals-cell">
                      <Utensils :size="13" :stroke-width="2.2" />
                      <span class="font-data-mono font-bold">{{ day.total_meals_sold }}</span>
                    </div>
                  </td>

                  <!-- Average Ticket (AOV) -->
                  <td>
                    <span class="font-data-mono aov-text text-muted">
                      ZMW {{ calculateAOV(day) }}
                    </span>
                  </td>

                  <!-- Relative volume bar -->
                  <td class="text-right">
                    <div class="volume-bar-track">
                      <div
                        class="volume-bar-fill"
                        :style="{ width: getRelativeVolumePercent(day.total_revenue_zmw) + '%' }"
                      ></div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- History Summary Footer -->
          <div class="calendar-footer-strip">
            <div class="stat-bubble">
              <span class="stat-caption">CUMULATIVE REVENUE</span>
              <span class="stat-val font-data-mono">
                ZMW {{ formatMoney(totalHistoryRevenue) }}
              </span>
            </div>
            <div class="stat-bubble">
              <span class="stat-caption">TOTAL MEALS SERVED</span>
              <span class="stat-val font-data-mono">
                {{ totalHistoryMeals }} plates
              </span>
            </div>
            <div class="stat-bubble">
              <span class="stat-caption">TOTAL REGISTER ORDERS</span>
              <span class="stat-val font-data-mono">
                {{ totalHistoryOrders }} tickets
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- ======================================================== -->
    <!-- RESTOCK MODAL / DIALOG                                   -->
    <!-- ======================================================== -->
    <div v-if="showRestockModal" class="bento-modal-backdrop" @click.self="showRestockModal = false">
      <div class="restock-modal-card card-bento animate-bento-in">
        <div class="modal-header">
          <div class="modal-title-row">
            <Boxes :size="18" :stroke-width="2.4" />
            <h3>Restock Beverage Crate</h3>
          </div>
          <button class="modal-close-btn" @click="showRestockModal = false">
            <X :size="16" :stroke-width="2.5" />
          </button>
        </div>

        <form @submit.prevent="submitRestock" class="restock-form">
          <div class="form-group">
            <label>Select Beverage</label>
            <select
              v-model="restockForm.drinkId"
              class="bento-select"
              required
              @change="onRestockDrinkSelect"
            >
              <option v-for="d in drinkList" :key="d.id" :value="d.id">
                {{ d.name }} (Current: {{ d.stock_quantity }} in crate)
              </option>
            </select>
          </div>

          <div class="form-row-two">
            <div class="form-group">
              <label>Stock Quantity (Units)</label>
              <input
                v-model.number="restockForm.stockQuantity"
                type="number"
                min="0"
                required
                class="bento-input font-data-mono"
              />
            </div>

            <div class="form-group">
              <label>Low-Stock Threshold</label>
              <input
                v-model.number="restockForm.threshold"
                type="number"
                min="1"
                required
                class="bento-input font-data-mono"
              />
            </div>
          </div>

          <!-- Quick Add shortcuts -->
          <div class="preset-shortcuts">
            <span class="preset-label">Add quick crate:</span>
            <button
              type="button"
              class="btn-pill-outline btn-micro"
              @click="restockForm.stockQuantity += 12"
            >
              +12 Cans/Bottles
            </button>
            <button
              type="button"
              class="btn-pill-outline btn-micro"
              @click="restockForm.stockQuantity += 24"
            >
              +24 Full Crate
            </button>
          </div>

          <div v-if="restockError" class="badge-pill badge-pill-red form-error">
            <AlertCircle :size="13" :stroke-width="2.5" />
            <span>{{ restockError }}</span>
          </div>

          <div class="modal-actions">
            <button
              type="button"
              class="btn-pill-outline cancel-btn"
              @click="showRestockModal = false"
            >
              Cancel
            </button>
            <button
              type="submit"
              class="btn-pill-primary submit-btn"
              :disabled="isUpdatingStock"
            >
              <span v-if="isUpdatingStock">Saving changes...</span>
              <span v-else>Update Beverage Stock</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import {
  Crown,
  TrendingUp,
  Banknote,
  Zap,
  RefreshCw,
  Boxes,
  Calendar,
  Wine,
  Utensils,
  Plus,
  Edit3,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  X,
  Loader2,
} from 'lucide-vue-next';
import { api } from '../services/api.js';
import { offlineQueue } from '../stores/offlineQueue.js';

// Animated numeric counter state
const animatedMetrics = reactive({
  todayTotal: 0,
  todayCash: 0,
  settlementBalance: 0,
});

// Summary Data
const summaryData = reactive({
  today_total_revenue_zmw: 0,
  today_cash_revenue_zmw: 0,
  settlement_account_balance_zmw: 0,
  today_orders_count: 0,
  low_stock_alerts: [],
});

// Inventory & Calendar states
const drinkList = ref([]);
const calendarData = ref([]);
const isLoadingSummary = ref(false);
const isLoadingDrinks = ref(false);
const isLoadingCalendar = ref(false);
const isUpdatingStock = ref(false);
const lastUpdatedTime = ref('');

// Calendar filter
const currentMonthNumber = new Date().getMonth() + 1;
const selectedMonthFilter = ref(null);

// Restock Modal State
const showRestockModal = ref(false);
const restockError = ref('');
const restockForm = reactive({
  drinkId: null,
  stockQuantity: 0,
  threshold: 10,
});

// Format currency
const formatMoney = (val) => {
  return Number(val || 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

// Smooth count-up animation
const animateNumber = (targetKey, toValue, duration = 600) => {
  const fromValue = animatedMetrics[targetKey];
  const startTime = performance.now();

  const step = (now) => {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease-out cubic
    const easeProgress = 1 - Math.pow(1 - progress, 3);
    animatedMetrics[targetKey] = fromValue + (toValue - fromValue) * easeProgress;

    if (progress < 1) {
      requestAnimationFrame(step);
    } else {
      animatedMetrics[targetKey] = toValue;
    }
  };

  requestAnimationFrame(step);
};

// Fetch Dashboard Summary
const fetchSummary = async () => {
  isLoadingSummary.value = true;
  try {
    const res = await api.getDashboardSummary();
    summaryData.today_total_revenue_zmw = res.today_total_revenue_zmw;
    summaryData.today_cash_revenue_zmw = res.today_cash_revenue_zmw;
    summaryData.settlement_account_balance_zmw = res.settlement_account_balance_zmw;
    summaryData.today_orders_count = res.today_orders_count;
    summaryData.low_stock_alerts = res.low_stock_alerts || [];

    // Trigger smooth counter animations
    animateNumber('todayTotal', res.today_total_revenue_zmw);
    animateNumber('todayCash', res.today_cash_revenue_zmw);
    animateNumber('settlementBalance', res.settlement_account_balance_zmw);

    lastUpdatedTime.value = new Date().toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch (err) {
    console.error('Failed to load dashboard summary:', err);
  } finally {
    isLoadingSummary.value = false;
  }
};

// Fetch Drink Inventory
const fetchDrinks = async () => {
  isLoadingDrinks.value = true;
  try {
    const data = await api.getDrinkInventory();
    drinkList.value = data;
  } catch (err) {
    console.error('Failed to load drink inventory:', err);
  } finally {
    isLoadingDrinks.value = false;
  }
};

// Fetch Calendar Analytics
const fetchCalendar = async (month = null) => {
  isLoadingCalendar.value = true;
  try {
    const year = new Date().getFullYear();
    const data = await api.getDashboardCalendar(month, month ? year : null);
    calendarData.value = data || [];
  } catch (err) {
    console.error('Failed to load calendar analytics:', err);
  } finally {
    isLoadingCalendar.value = false;
  }
};

const filterMonth = (month) => {
  selectedMonthFilter.value = month;
  fetchCalendar(month);
};

const onQueueSynced = () => {
  console.log('[OwnerDashboard] Queue sync detected. Refreshing telemetry...');
  loadAllDashboardData();
};

onMounted(() => {
  loadAllDashboardData();
  window.addEventListener('bomapos:queue-synced', onQueueSynced);
});

onUnmounted(() => {
  window.removeEventListener('bomapos:queue-synced', onQueueSynced);
});

// Computed properties
const lowStockItems = computed(() => {
  return drinkList.value.filter(
    (d) => d.is_low_stock || d.stock_quantity <= d.low_stock_threshold
  );
});

const sortedCalendarData = computed(() => {
  // Show most recent dates first
  return [...calendarData.value].sort((a, b) => (a.date < b.date ? 1 : -1));
});

const maxRevenueInCalendar = computed(() => {
  if (calendarData.value.length === 0) return 1;
  return Math.max(...calendarData.value.map((d) => d.total_revenue_zmw), 1);
});

const totalHistoryRevenue = computed(() => {
  return calendarData.value.reduce((sum, d) => sum + d.total_revenue_zmw, 0);
});

const totalHistoryMeals = computed(() => {
  return calendarData.value.reduce((sum, d) => sum + d.total_meals_sold, 0);
});

const totalHistoryOrders = computed(() => {
  return calendarData.value.reduce((sum, d) => sum + d.total_orders_count, 0);
});

// Helpers
const getStockPercentage = (drink) => {
  const max = Math.max(drink.low_stock_threshold * 2.5, 50);
  return Math.min(Math.round((drink.stock_quantity / max) * 100), 100);
};

const getProgressFillClass = (drink) => {
  if (drink.stock_quantity === 0 || drink.stock_quantity <= 3) return 'fill-red';
  if (drink.stock_quantity <= drink.low_stock_threshold) return 'fill-ochre';
  return 'fill-mint';
};

const getDrinkBadgeClass = (drink) => {
  if (drink.stock_quantity === 0) return 'badge-pill-red';
  if (drink.stock_quantity <= drink.low_stock_threshold) return 'badge-pill-ochre';
  return 'badge-pill-mint';
};

const getDrinkStatusLabel = (drink) => {
  if (drink.stock_quantity === 0) return 'DEPLETED';
  if (drink.stock_quantity <= drink.low_stock_threshold) return 'LOW STOCK';
  return 'HEALTHY';
};

const getRelativeVolumePercent = (rev) => {
  return Math.max(Math.round((rev / maxRevenueInCalendar.value) * 100), 8);
};

const calculateAOV = (day) => {
  if (!day.total_orders_count) return '0.00';
  return (day.total_revenue_zmw / day.total_orders_count).toFixed(2);
};

const isToday = (dateStr) => {
  const today = new Date().toISOString().split('T')[0];
  return dateStr === today;
};

// Quick Stock Increment (+6 or +24 directly)
const quickIncrementStock = async (drink, addQty) => {
  isUpdatingStock.value = true;
  try {
    const newQty = drink.stock_quantity + addQty;
    await api.updateDrinkInventory(drink.id, {
      stock_quantity: newQty,
    });
    drink.stock_quantity = newQty;
    drink.is_low_stock = newQty <= drink.low_stock_threshold;
    await fetchSummary();
  } catch (err) {
    alert(err.message || 'Failed to update stock quantity');
  } finally {
    isUpdatingStock.value = false;
  }
};

// Open Restock Modal
const openRestockModal = (drink = null) => {
  restockError.value = '';
  if (drink) {
    restockForm.drinkId = drink.id;
    restockForm.stockQuantity = drink.stock_quantity;
    restockForm.threshold = drink.low_stock_threshold;
  } else if (drinkList.value.length > 0) {
    const first = drinkList.value[0];
    restockForm.drinkId = first.id;
    restockForm.stockQuantity = first.stock_quantity;
    restockForm.threshold = first.low_stock_threshold;
  }
  showRestockModal.value = true;
};

const onRestockDrinkSelect = () => {
  const selected = drinkList.value.find((d) => d.id === restockForm.drinkId);
  if (selected) {
    restockForm.stockQuantity = selected.stock_quantity;
    restockForm.threshold = selected.low_stock_threshold;
  }
};

const submitRestock = async () => {
  if (!restockForm.drinkId) return;
  isUpdatingStock.value = true;
  restockError.value = '';

  try {
    await api.updateDrinkInventory(restockForm.drinkId, {
      stock_quantity: restockForm.stockQuantity,
      low_stock_threshold: restockForm.threshold,
    });
    showRestockModal.value = false;
    await Promise.all([fetchDrinks(), fetchSummary()]);
  } catch (err) {
    restockError.value = err.message || 'Failed to save inventory updates';
  } finally {
    isUpdatingStock.value = false;
  }
};
</script>

<style scoped>
.owner-bento-viewport {
  height: calc(100vh - 64px);
  overflow-y: auto;
  padding: 24px;
}

.owner-bento-container {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ======================================================== */
/* HERO BENTO CARD (#0B2416)                                */
/* ======================================================== */
.hero-bento-card {
  padding: 24px 28px;
}

.hero-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding-bottom: 20px;
  margin-bottom: 22px;
}

.hero-brand-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.hero-emblem-badge {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background-color: var(--color-primary-accent);
  color: #082515;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(52, 168, 100, 0.35);
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hero-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #FFFFFF;
}

.hero-caption {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.65);
  margin-top: 2px;
}

.hero-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sync-time-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  background-color: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 6px 12px;
  border-radius: var(--radius-pill);
}

.sync-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--color-primary-accent);
}

.hero-refresh-btn {
  background-color: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.16);
  color: #FFFFFF;
  padding: 6px 16px;
}

.hero-refresh-btn:hover:not(:disabled) {
  background-color: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.3);
}

.spin-anim {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Metric KPI Bento Grid */
.hero-metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}

.metric-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 125px;
  transition: all 0.2s ease;
}

.metric-card:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.14);
}

.metric-card.lenco-accent {
  background: radial-gradient(circle at 90% 10%, rgba(52, 168, 100, 0.15), rgba(255, 255, 255, 0.04) 60%);
  border-color: rgba(52, 168, 100, 0.25);
}

.metric-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.metric-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.7);
}

.metric-icon-bubble {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
}

.metric-icon-bubble.cash {
  color: #FBBF24;
}

.metric-icon-bubble.lenco {
  background: rgba(52, 168, 100, 0.2);
  color: var(--color-primary-accent);
}

.metric-value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 10px 0 6px;
}

.currency-prefix {
  font-size: 14px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.6);
}

.metric-num {
  font-size: 28px;
  font-weight: 800;
  color: #FFFFFF;
  letter-spacing: -0.02em;
}

.text-mint {
  color: var(--color-primary-accent) !important;
}

.metric-footer {
  display: flex;
  align-items: center;
}

.metric-sub-detail {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}

.hero-offline-queue-strip {
  margin-top: 18px;
  background-color: rgba(180, 120, 24, 0.15);
  border: 1px solid rgba(180, 120, 24, 0.35);
  border-radius: 12px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.queue-strip-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #FFFFFF;
}

.text-ochre {
  color: var(--color-tertiary-accent);
}

.sync-strip-btn {
  padding: 5px 14px;
  font-size: 11px;
  background-color: var(--color-tertiary);
  border-color: var(--color-tertiary);
}

.sync-strip-btn:hover:not(:disabled) {
  background-color: var(--color-tertiary-accent);
}

/* ======================================================== */
/* SECONDARY BENTO GRID                                     */
/* ======================================================== */
.secondary-bento-grid {
  display: grid;
  grid-template-columns: 57% 43%;
  gap: 20px;
}

@media (max-width: 1240px) {
  .secondary-bento-grid {
    grid-template-columns: 1fr;
  }
}

.inventory-watcher-card,
.calendar-history-card {
  padding: 22px;
  display: flex;
  flex-direction: column;
}

.module-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.module-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.module-icon-shield {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background-color: var(--color-primary-container);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.module-icon-shield.calendar {
  background-color: var(--color-tertiary-container);
  color: var(--color-tertiary);
}

.module-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.module-caption {
  font-size: 11px;
  color: var(--color-on-surface-variant);
  margin-top: 2px;
}

.restock-quick-btn {
  font-size: 12px;
  padding: 6px 14px;
}

/* Low Stock Alert Banner */
.low-stock-alert-banner {
  background-color: var(--color-error-container);
  border: 1px solid rgba(196, 50, 66, 0.3);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.alert-icon {
  color: var(--color-error);
  flex-shrink: 0;
}

.alert-text {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: var(--color-on-error-container);
}

.alert-text strong {
  font-weight: 700;
}

/* Tables */
.inventory-table-container,
.calendar-table-container {
  overflow-x: auto;
  border: 1px solid var(--color-border-card);
  border-radius: 10px;
  background: var(--color-surface);
  flex: 1;
}

.bento-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 12.5px;
}

.bento-table thead th {
  background-color: var(--color-surface-dim);
  padding: 8px 10px;
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--color-on-surface-variant);
  border-bottom: 1px solid var(--color-border-card);
  white-space: nowrap;
}

.bento-table tbody td {
  padding: 10px 10px;
  border-bottom: 1px solid var(--color-surface-dim);
  vertical-align: middle;
}

.bento-table tbody tr:hover {
  background-color: var(--color-surface-container-low);
}

.bento-table tbody tr.row-warning {
  background-color: rgba(180, 120, 24, 0.04);
}

.bento-table tbody tr.row-today {
  background-color: rgba(20, 77, 47, 0.04);
}

.text-right {
  text-align: right;
}

.drink-item-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.drink-icon-box {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background-color: var(--color-surface-dim);
  color: var(--color-on-surface);
  display: flex;
  align-items: center;
  justify-content: center;
}

.drink-name {
  font-weight: 600;
  color: var(--color-on-surface);
}

.table-price {
  font-weight: 600;
  color: var(--color-primary);
}

.stock-progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stock-number {
  min-width: 24px;
}

.mini-progress-track {
  width: 60px;
  height: 6px;
  background-color: var(--color-surface-dim);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: var(--radius-pill);
}

.mini-progress-fill.fill-mint {
  background-color: var(--color-primary-accent);
}

.mini-progress-fill.fill-ochre {
  background-color: var(--color-tertiary-accent);
}

.mini-progress-fill.fill-red {
  background-color: var(--color-error);
}

.text-muted {
  color: var(--color-on-surface-muted);
}

.font-bold {
  font-weight: 700;
}

.inline-restock-actions {
  display: flex;
  justify-content: flex-end;
  gap: 5px;
}

.btn-micro {
  padding: 3px 8px;
  font-size: 11px;
}

.edit-btn {
  padding: 3px 6px;
}

/* Month filter in Calendar */
.month-pill-filter {
  display: flex;
  align-items: center;
  gap: 6px;
}

.filter-label {
  font-size: 11px;
  color: var(--color-on-surface-muted);
}

.filter-pill {
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-on-surface-variant);
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-pill.active {
  background-color: var(--color-tertiary);
  color: #FFFFFF;
  border-color: var(--color-tertiary);
}

.date-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.today-pill {
  font-size: 9px;
  padding: 1px 6px;
}

.revenue-text {
  color: var(--color-primary);
}

.meals-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-on-surface);
}

.volume-bar-track {
  width: 100%;
  max-width: 90px;
  height: 6px;
  background-color: var(--color-surface-dim);
  border-radius: var(--radius-pill);
  overflow: hidden;
  margin-left: auto;
}

.volume-bar-fill {
  height: 100%;
  background-color: var(--color-tertiary-accent);
  border-radius: var(--radius-pill);
}

/* Calendar Summary Strip */
.calendar-footer-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border-card);
}

.stat-bubble {
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
}

.stat-caption {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--color-on-surface-muted);
}

.stat-val {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-on-surface);
  margin-top: 2px;
}

/* Loading & Empty States */
.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 8px;
  color: var(--color-on-surface-variant);
  font-size: 13px;
}

/* ======================================================== */
/* RESTOCK MODAL                                            */
/* ======================================================== */
.bento-modal-backdrop {
  position: fixed;
  inset: 0;
  background-color: rgba(12, 26, 18, 0.6);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.restock-modal-card {
  width: 100%;
  max-width: 480px;
  padding: 24px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.modal-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-primary);
}

.modal-title-row h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.modal-close-btn {
  background: transparent;
  border: none;
  color: var(--color-on-surface-muted);
  cursor: pointer;
}

.restock-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-on-surface-variant);
}

.bento-select,
.bento-input {
  height: 44px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  padding: 0 16px;
  font-size: 13px;
  color: var(--color-on-surface);
  outline: none;
}

.bento-select:focus,
.bento-input:focus {
  background-color: var(--color-surface);
  border-color: var(--color-primary-accent);
  box-shadow: 0 0 0 3px rgba(52, 168, 100, 0.15);
}

.form-row-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.preset-shortcuts {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preset-label {
  font-size: 11px;
  color: var(--color-on-surface-muted);
}

.form-error {
  justify-content: center;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

.cancel-btn,
.submit-btn {
  padding: 10px 20px;
}

@media (max-width: 900px) {
  .hero-metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
