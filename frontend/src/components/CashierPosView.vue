<template>
  <div class="pos-bento-layout bg-hatch-diagonal">
    <!-- ======================================================== -->
    <!-- LEFT PANEL: 70% Menu Bento Grid & Category Filters       -->
    <!-- ======================================================== -->
    <section class="menu-zone">
      <!-- Top Bento Control Bar -->
      <div class="menu-control-bar card-bento animate-bento-in">
        <!-- Live Instant Search -->
        <div class="search-capsule">
          <Search class="search-icon" :size="16" :stroke-width="2.4" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search menu items, beverages, sides..."
            class="search-input"
          />
          <button v-if="searchQuery" class="clear-search-btn" @click="searchQuery = ''">
            <X :size="14" :stroke-width="2.5" />
          </button>
        </div>

        <!-- Bento Category Capsule Pills -->
        <div class="category-capsule-row">
          <button
            v-for="cat in categories"
            :key="cat.value"
            class="category-pill"
            :class="{ active: selectedCategory === cat.value }"
            @click="selectedCategory = cat.value"
          >
            <component :is="cat.iconComponent" :size="14" :stroke-width="2.2" />
            <span>{{ cat.label }}</span>
            <span class="pill-count font-data-mono">{{ getCategoryCount(cat.value) }}</span>
          </button>
        </div>
      </div>

      <!-- Offline Alert Banner -->
      <div v-if="!offlineQueue.effectiveOnline" class="offline-pos-banner animate-bento-in">
        <WifiOff :size="15" :stroke-width="2.4" />
        <div class="banner-text">
          <strong>Offline Mode Active:</strong>
          <span>Orders will be securely queued locally and auto-synced once internet is restored.</span>
        </div>
      </div>

      <!-- Products Bento Grid -->
      <div class="products-scroll-area">
        <div v-if="isLoadingMenu" class="loading-state">
          <Loader2 class="spinner-icon" :size="24" :stroke-width="2.2" />
          <p>Syncing menu inventory...</p>
        </div>

        <div v-else-if="filteredMenu.length === 0" class="empty-state card-bento">
          <SearchX class="empty-state-icon" :size="32" :stroke-width="1.8" />
          <h4>No items found</h4>
          <p>No results match "{{ searchQuery }}"</p>
        </div>

        <div v-else class="products-bento-grid">
          <div
            v-for="item in filteredMenu"
            :key="item.id"
            class="product-bento-card card-bento animate-bento-in"
            :class="{
              'is-disabled': isItemDisabled(item),
              'is-critical': getStockStatus(item) === 'CRITICAL LOW',
            }"
            @click="handleCardClick(item)"
          >
            <!-- Card Header: Category & Stock Capsule Pill -->
            <div class="card-header-line">
              <span class="badge-pill badge-pill-charcoal item-cat-badge">
                {{ formatCategory(item.category) }}
              </span>

              <!-- Live Drink Crate Pill -->
              <span
                v-if="item.drink_inventory"
                class="badge-pill"
                :class="getStockPillClass(item)"
              >
                <Package :size="11" :stroke-width="2.2" />
                {{ getStockBadgeText(item) }}
              </span>
            </div>

            <!-- Card Body -->
            <div class="card-body-content">
              <h3 class="item-name-heading">{{ item.name }}</h3>
              <p class="item-sub-caption">{{ getItemDescription(item) }}</p>
            </div>

            <!-- Card Footer: Kwacha Price & Add Action -->
            <div class="card-footer-line">
              <div class="price-pill-tag">
                <span class="currency-label">ZMW</span>
                <span class="price-number font-data-mono">{{ item.price_zmw.toFixed(2) }}</span>
              </div>

              <button
                class="btn-pill-primary add-card-btn"
                :disabled="isItemDisabled(item)"
              >
                <Plus v-if="!isItemDisabled(item)" :size="13" :stroke-width="2.5" />
                <span>{{ isItemDisabled(item) ? 'Out of Stock' : 'Add' }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ======================================================== -->
    <!-- RIGHT PANEL: 30% Active Cart & Inverted Hero Checkout     -->
    <!-- ======================================================== -->
    <aside class="cart-zone">
      <!-- Top Order Info Card (Standard Bento) -->
      <div class="cart-header-card card-bento">
        <div class="order-meta-cluster">
          <div class="order-id-line">
            <span class="order-badge font-data-mono">TICKET #{{ cartState.orderNumber }}</span>
            <span class="badge-pill badge-pill-mint">
              <Users :size="11" :stroke-width="2.2" />
              {{ cartState.tableNumber }}
            </span>
          </div>
          <span class="server-label">Cashier: {{ authState.user?.username }}</span>
        </div>

        <button
          v-if="cartState.items.length > 0"
          class="btn-pill-outline clear-cart-action"
          @click="cartState.clearCart"
          title="Clear active items"
        >
          <RotateCcw :size="11" :stroke-width="2.2" />
          <span>Reset</span>
        </button>
      </div>

      <!-- Cart Items List -->
      <div class="cart-items-card card-bento">
        <div v-if="cartState.items.length === 0" class="cart-empty-view">
          <div class="empty-icon-circle">
            <ShoppingBag :size="22" :stroke-width="1.8" />
          </div>
          <h4>Register Ready</h4>
          <p>Tap items from the bento grid on the left to add to this order.</p>
        </div>

        <div v-else class="cart-line-list">
          <div
            v-for="item in cartState.items"
            :key="item.id"
            class="cart-line-item"
          >
            <div class="item-info-col">
              <span class="line-name">{{ item.name }}</span>
              <span class="line-rate font-data-mono">K{{ item.price_zmw.toFixed(2) }} each</span>
            </div>

            <!-- Capsule Quantity Stepper -->
            <div class="stepper-capsule">
              <button
                class="step-btn minus"
                @click="cartState.decreaseQty(item.id)"
              >
                <Minus :size="11" :stroke-width="2.5" />
              </button>
              <span class="step-num font-data-mono">{{ item.quantity }}</span>
              <button
                class="step-btn plus"
                :disabled="item.quantity >= item.max_stock"
                @click="cartState.increaseQty(item.id)"
              >
                <Plus :size="11" :stroke-width="2.5" />
              </button>
            </div>

            <div class="line-price-col">
              <span class="line-total font-data-mono">
                K{{ (item.price_zmw * item.quantity).toFixed(2) }}
              </span>
              <button class="remove-btn" @click="cartState.removeItem(item.id)">
                <X :size="12" :stroke-width="2.2" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- INVERTED HERO TENDER CARD (PandaStays Tactile Signature: #0B2416) -->
      <div class="checkout-hero-card card-bento-hero bg-topo-dark">
        <!-- Breakdown Lines -->
        <div class="hero-breakdown">
          <div class="hero-line">
            <span class="hero-label">Items Subtotal</span>
            <span class="hero-val font-data-mono">K{{ cartState.subtotalAmount.toFixed(2) }}</span>
          </div>

          <div class="hero-line tax-highlight">
            <span class="hero-label">16% ZRA VAT (Included)</span>
            <span class="hero-val font-data-mono">K{{ cartState.vatAmount.toFixed(2) }}</span>
          </div>

          <div class="hero-line toggle-row">
            <label class="service-checkbox-label">
              <input type="checkbox" v-model="cartState.serviceChargeEnabled" />
              <span>Service Charge (5%)</span>
            </label>
            <span class="hero-val font-data-mono">K{{ cartState.serviceChargeAmount.toFixed(2) }}</span>
          </div>

          <div class="hero-divider"></div>

          <!-- Total Due -->
          <div class="hero-total-line">
            <div class="total-heading-stack">
              <span class="over-caption">TOTAL AMOUNT DUE</span>
              <span class="sub-caption">Zambian Kwacha</span>
            </div>
            <span class="hero-grand-total font-data-mono">
              K{{ cartState.totalAmount.toFixed(2) }}
            </span>
          </div>
        </div>

        <!-- Tender Actions (PandaStays Capsule Primary Buttons) -->
        <div class="hero-actions-grid">
          <button
            class="btn-pill-outline tender-pill-cash"
            :disabled="cartState.items.length === 0 || isProcessingOrder"
            @click="handleCashCheckout"
          >
            <Banknote :size="16" :stroke-width="2.2" />
            <span>Cash Drawer</span>
          </button>

          <button
            class="btn-pill-primary tender-pill-momo"
            :disabled="cartState.items.length === 0 || isProcessingOrder"
            @click="showMobileMoneyModal = true"
          >
            <Zap :size="16" :stroke-width="2.4" />
            <span>MoMo (Lenco)</span>
          </button>
        </div>
      </div>
    </aside>

    <!-- Cash Receipt Modal (Bento Inverted) -->
    <div v-if="cashSuccessReceipt" class="bento-modal-backdrop" @click="cashSuccessReceipt = null">
      <div class="bento-receipt-card card-bento-hero bg-topo-dark" @click.stop>
        <div class="receipt-icon-circle">
          <CheckCircle2 :size="28" :stroke-width="2.5" />
        </div>
        <h3 class="receipt-title">Order Paid via Cash</h3>
        <p class="receipt-sub font-data-mono">ZRA EFD FISCAL RECEIPT • {{ cashSuccessReceipt.timestamp }}</p>

        <!-- Offline Sync Badge -->
        <div v-if="cashSuccessReceipt.isOffline" class="offline-receipt-pill-row">
          <span class="badge-pill badge-pill-ochre font-data-mono">
            ⚡ Saved offline. Will sync when online.
          </span>
        </div>

        <div class="receipt-meta-box card-bento">
          <div class="meta-row">
            <span>Ticket Ref:</span>
            <strong class="font-data-mono">#{{ cashSuccessReceipt.orderId }}</strong>
          </div>
          <div class="meta-row">
            <span>Operator:</span>
            <strong>{{ authState.user?.username }}</strong>
          </div>
          <div class="meta-row">
            <span>Tender Type:</span>
            <span class="badge-pill" :class="cashSuccessReceipt.isOffline ? 'badge-pill-ochre' : 'badge-pill-mint'">
              {{ cashSuccessReceipt.isOffline ? 'CASH (OFFLINE QUEUED)' : 'CASH DRAWER' }}
            </span>
          </div>
          <div class="meta-divider"></div>
          <div class="meta-row total-highlight">
            <span>Total Collected:</span>
            <strong class="font-data-mono text-emerald">K{{ cashSuccessReceipt.total.toFixed(2) }}</strong>
          </div>
        </div>

        <button class="btn-pill-primary receipt-done-btn" @click="cashSuccessReceipt = null">
          <span>Complete & Next Ticket</span>
          <ArrowRight :size="15" :stroke-width="2.2" />
        </button>
      </div>
    </div>

    <!-- Mobile Money Modal -->
    <MobileMoneyModal
      v-if="showMobileMoneyModal"
      :total-amount="cartState.totalAmount"
      @close="showMobileMoneyModal = false"
      @order-completed="handleOrderSuccess"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import {
  Search,
  X,
  Plus,
  Minus,
  Utensils,
  Beer,
  Salad,
  LayoutGrid,
  Package,
  ShoppingBag,
  Users,
  RotateCcw,
  Banknote,
  Zap,
  CheckCircle2,
  ArrowRight,
  SearchX,
  Loader2,
  WifiOff,
} from 'lucide-vue-next';
import { api } from '../services/api.js';
import { authState } from '../stores/auth.js';
import { cartState } from '../stores/cart.js';
import { offlineQueue } from '../stores/offlineQueue.js';
import MobileMoneyModal from './MobileMoneyModal.vue';

const categories = [
  { label: 'All Items', value: 'all', iconComponent: LayoutGrid },
  { label: 'Meals & Platters', value: 'meal', iconComponent: Utensils },
  { label: 'Beer & Cold Drinks', value: 'drink', iconComponent: Beer },
  { label: 'Sides & Relishes', value: 'extra', iconComponent: Salad },
];

const menuItems = ref([]);
const selectedCategory = ref('all');
const searchQuery = ref('');
const isLoadingMenu = ref(true);
const isProcessingOrder = ref(false);
const showMobileMoneyModal = ref(false);
const cashSuccessReceipt = ref(null);

const fetchMenu = async () => {
  isLoadingMenu.value = true;
  try {
    const data = await api.getMenu();
    menuItems.value = data;
  } catch (err) {
    console.error('Failed to load menu items:', err);
  } finally {
    isLoadingMenu.value = false;
  }
};

const onQueueSynced = () => {
  console.log('[CashierPosView] Queue sync event detected. Refreshing menu stock...');
  fetchMenu();
};

onMounted(() => {
  fetchMenu();
  window.addEventListener('bomapos:queue-synced', onQueueSynced);
});

onUnmounted(() => {
  window.removeEventListener('bomapos:queue-synced', onQueueSynced);
});

const getCategoryCount = (category) => {
  if (category === 'all') return menuItems.value.length;
  return menuItems.value.filter((i) => i.category === category).length;
};

const formatCategory = (cat) => {
  if (cat === 'meal') return 'Platter';
  if (cat === 'drink') return 'Beverage';
  return 'Side / Relish';
};

const getItemDescription = (item) => {
  if (item.category === 'drink') return 'Chilled bottle / can';
  if (item.name.includes('Nshima')) return 'With seasonal village greens & relish';
  return 'Prepared fresh daily to order';
};

const getStockStatus = (item) => {
  if (!item.drink_inventory) return 'HEALTHY';
  const qty = item.drink_inventory.stock_quantity;
  const threshold = item.drink_inventory.low_stock_threshold;
  if (qty === 0) return 'DEPLETED';
  if (qty <= Math.max(2, Math.floor(threshold / 2))) return 'CRITICAL LOW';
  if (qty <= threshold) return 'WARNING';
  return 'HEALTHY';
};

const getStockPillClass = (item) => {
  const status = getStockStatus(item);
  if (status === 'DEPLETED' || status === 'CRITICAL LOW') return 'badge-pill-red';
  if (status === 'WARNING') return 'badge-pill-ochre';
  return 'badge-pill-mint';
};

const getStockBadgeText = (item) => {
  const qty = item.drink_inventory.stock_quantity;
  if (qty === 0) return 'Empty';
  return `${qty} in crate`;
};

const isItemDisabled = (item) => {
  if (!item.is_available) return true;
  if (item.drink_inventory && item.drink_inventory.stock_quantity === 0) return true;
  return false;
};

const filteredMenu = computed(() => {
  let list = menuItems.value;
  if (selectedCategory.value !== 'all') {
    list = list.filter((i) => i.category === selectedCategory.value);
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase().trim();
    list = list.filter(
      (i) => i.name.toLowerCase().includes(q) || i.category.toLowerCase().includes(q)
    );
  }
  return list;
});

const handleCardClick = (item) => {
  if (isItemDisabled(item)) return;
  cartState.addItem(item);
};

const handleCashCheckout = async () => {
  if (cartState.items.length === 0) return;
  isProcessingOrder.value = true;
  try {
    const payload = {
      cashier_id: authState.user.id,
      payment_method: 'cash',
      items: cartState.items.map((i) => ({
        menu_item_id: i.id,
        quantity: i.quantity,
      })),
    };

    const res = await api.createOrder(payload, cartState.items);
    cashSuccessReceipt.value = {
      orderId: res.id,
      total: res.total_amount,
      timestamp: new Date().toLocaleTimeString(),
      isOffline: !!res.is_offline,
    };

    // If offline, optimistically decrement local drink inventory so cashier can't oversell
    if (res.is_offline) {
      cartState.items.forEach((cItem) => {
        const mItem = menuItems.value.find((m) => m.id === cItem.id);
        if (mItem && mItem.drink_inventory) {
          mItem.drink_inventory.stock_quantity = Math.max(
            0,
            mItem.drink_inventory.stock_quantity - cItem.quantity
          );
          mItem.drink_inventory.is_low_stock =
            mItem.drink_inventory.stock_quantity <= mItem.drink_inventory.low_stock_threshold;
        }
      });
    }

    cartState.clearCart();
    if (!res.is_offline) {
      await fetchMenu();
    }
  } catch (err) {
    alert(err.message || 'Failed to process cash order.');
  } finally {
    isProcessingOrder.value = false;
  }
};

const handleOrderSuccess = async () => {
  await fetchMenu();
};
</script>

<style scoped>
.pos-bento-layout {
  display: flex;
  height: calc(100vh - 64px);
  overflow: hidden;
  padding: 16px;
  gap: 16px;
}

/* ======================================================== */
/* LEFT PANEL: 70% Menu Zone                                */
/* ======================================================== */
.menu-zone {
  flex: 7;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: hidden;
}

.menu-control-bar {
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.offline-pos-banner {
  background-color: var(--color-tertiary-container);
  border: 1px solid rgba(180, 120, 24, 0.4);
  border-radius: 12px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--color-on-tertiary-container);
  font-size: 12px;
}

.offline-pos-banner .banner-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

.offline-pos-banner .banner-text strong {
  font-weight: 700;
}

.offline-receipt-pill-row {
  margin: 8px 0 12px;
  display: flex;
  justify-content: center;
}

.search-capsule {
  display: flex;
  align-items: center;
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  border-radius: var(--radius-pill);
  padding: 0 16px;
  height: 44px;
  transition: all 0.15s ease;
}

.search-capsule:focus-within {
  background-color: var(--color-surface);
  border-color: var(--color-primary-accent);
  box-shadow: 0 0 0 3px rgba(52, 168, 100, 0.15);
}

.search-icon {
  color: var(--color-on-surface-variant);
  margin-right: 10px;
}

.search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--color-on-surface);
  font-size: 14px;
  font-weight: 500;
}

.search-input::placeholder {
  color: var(--color-on-surface-muted);
}

.clear-search-btn {
  background: transparent;
  color: var(--color-on-surface-muted);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.category-capsule-row {
  display: flex;
  gap: 8px;
  overflow-x: auto;
}

.category-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  color: var(--color-on-surface-variant);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.category-pill.active {
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  border-color: var(--color-primary);
  box-shadow: 0 2px 8px rgba(20, 77, 47, 0.2);
}

.pill-count {
  font-size: 11px;
  background-color: rgba(0, 0, 0, 0.08);
  padding: 2px 6px;
  border-radius: var(--radius-pill);
}

.category-pill.active .pill-count {
  background-color: rgba(255, 255, 255, 0.2);
}

/* Products Bento Grid */
.products-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  gap: 12px;
  color: var(--color-on-surface-variant);
}

.spinner-icon {
  animation: spin 1s linear infinite;
  color: var(--color-primary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-state {
  padding: 40px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--color-on-surface-variant);
}

.empty-state-icon {
  color: var(--color-on-surface-muted);
}

.products-bento-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

.product-bento-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 160px;
  cursor: pointer;
  border-radius: var(--radius-bento);
}

.product-bento-card.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background-color: var(--color-surface-dim);
}

.product-bento-card.is-critical {
  border-color: var(--color-error);
}

.card-header-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.item-cat-badge {
  font-size: 10px;
}

.card-body-content {
  margin: 10px 0;
}

.item-name-heading {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-on-surface);
  line-height: 1.3;
}

.item-sub-caption {
  font-size: 11px;
  color: var(--color-on-surface-variant);
  margin-top: 4px;
}

.card-footer-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--color-border-card);
  padding-top: 10px;
}

.price-pill-tag {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.currency-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-primary);
}

.price-number {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.add-card-btn {
  padding: 6px 14px;
  font-size: 12px;
}

/* ======================================================== */
/* RIGHT PANEL: 30% Active Cart & Hero Inversion            */
/* ======================================================== */
.cart-zone {
  flex: 3;
  min-width: 360px;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Top Ticket Header */
.cart-header-card {
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.order-meta-cluster {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.order-id-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.order-badge {
  font-size: 14px;
  font-weight: 800;
  color: var(--color-primary);
}

.server-label {
  font-size: 11px;
  color: var(--color-on-surface-variant);
}

.clear-cart-action {
  font-size: 11px;
  padding: 4px 12px;
}

/* Cart Items Card */
.cart-items-card {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}

.cart-empty-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--color-on-surface-variant);
  padding: 20px;
}

.empty-icon-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background-color: var(--color-surface-dim);
  color: var(--color-on-surface-variant);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.cart-empty-view h4 {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.cart-empty-view p {
  font-size: 12px;
  color: var(--color-on-surface-variant);
  margin-top: 4px;
  max-width: 220px;
}

.cart-line-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cart-line-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background-color: var(--color-surface-dim);
  border-radius: var(--radius-subtle);
  border: 1px solid var(--color-border-card);
  gap: 8px;
}

.item-info-col {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.line-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-on-surface);
  line-height: 1.2;
}

.line-rate {
  font-size: 10px;
  color: var(--color-on-surface-variant);
  margin-top: 2px;
}

/* Stepper Capsule */
.stepper-capsule {
  display: flex;
  align-items: center;
  background-color: var(--color-surface);
  border: 1px solid var(--color-border-card);
  border-radius: var(--radius-pill);
  padding: 2px 4px;
  gap: 4px;
}

.step-btn {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background-color: var(--color-surface-dim);
  border: none;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-on-surface);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-btn:disabled {
  opacity: 0.3;
}

.step-num {
  font-size: 12px;
  font-weight: 700;
  min-width: 18px;
  text-align: center;
}

.line-price-col {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 75px;
  justify-content: flex-end;
}

.line-total {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary);
}

.remove-btn {
  background: transparent;
  border: none;
  color: var(--color-on-surface-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.remove-btn:hover {
  color: var(--color-error);
}

/* INVERTED HERO TENDER CARD (#0B2416) */
.checkout-hero-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-breakdown {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-line {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.tax-highlight {
  color: var(--color-primary-accent);
}

.service-checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.8);
}

.hero-divider {
  height: 1px;
  background-color: rgba(255, 255, 255, 0.12);
  margin: 4px 0;
}

.hero-total-line {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding-top: 4px;
}

.total-heading-stack {
  display: flex;
  flex-direction: column;
}

.over-caption {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: rgba(255, 255, 255, 0.6);
}

.sub-caption {
  font-size: 9px;
  color: rgba(255, 255, 255, 0.4);
}

.hero-grand-total {
  font-size: 28px;
  font-weight: 800;
  color: #FFFFFF;
}

/* Tender Action Buttons */
.hero-actions-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.tender-pill-cash {
  height: 48px;
  background-color: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.2);
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
}

.tender-pill-cash:hover:not(:disabled) {
  background-color: rgba(255, 255, 255, 0.15);
  border-color: rgba(255, 255, 255, 0.4);
}

.tender-pill-momo {
  height: 48px;
  background-color: var(--color-primary-accent);
  color: var(--color-on-primary-container);
  font-size: 13px;
  font-weight: 700;
}

.tender-pill-momo:hover:not(:disabled) {
  background-color: #2b9355;
  box-shadow: 0 4px 16px rgba(52, 168, 100, 0.4);
}

/* Modal Backdrop & Receipt */
.bento-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(8, 37, 21, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 16px;
}

.bento-receipt-card {
  width: 100%;
  max-width: 400px;
  padding: 28px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.receipt-icon-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background-color: var(--color-primary-accent);
  color: var(--color-on-primary-container);
  display: flex;
  align-items: center;
  justify-content: center;
}

.receipt-title {
  font-size: 20px;
  font-weight: 700;
  color: #FFFFFF;
}

.receipt-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
}

.receipt-meta-box {
  width: 100%;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
  font-size: 13px;
  color: var(--color-on-surface);
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta-divider {
  height: 1px;
  background-color: var(--color-border-card);
  margin: 4px 0;
}

.total-highlight {
  font-size: 15px;
}

.text-emerald {
  color: var(--color-primary);
  font-size: 18px;
}

.receipt-done-btn {
  width: 100%;
  height: 48px;
}
</style>
