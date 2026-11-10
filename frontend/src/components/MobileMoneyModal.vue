<template>
  <div class="momo-bento-backdrop" @click.self="$emit('close')">
    <div class="momo-bento-card card-bento animate-bento-in">
      <!-- Modal Header (Inverted Bento Hero Accent) -->
      <div class="momo-header-hero card-bento-hero bg-topo-dark">
        <div class="hero-header-content">
          <div class="momo-emblem">
            <Smartphone :size="18" :stroke-width="2.4" />
          </div>
          <div class="hero-titles">
            <h3>Zambian Mobile Money Tender</h3>
            <p>Direct Lenco STK Push Gateway • ZRA Fiscal Hash</p>
          </div>
        </div>
        <button class="hero-close-btn" @click="$emit('close')">
          <X :size="15" :stroke-width="2.5" />
        </button>
      </div>

      <!-- Amount Pill Banner -->
      <div class="amount-strip card-bento">
        <div class="strip-labels">
          <span class="label-caption">AMOUNT PAYABLE</span>
          <span class="label-sub">Zambian Kwacha</span>
        </div>
        <span class="strip-val font-data-mono">K{{ totalAmount.toFixed(2) }}</span>
      </div>

      <!-- Flow Container -->
      <div class="momo-body-area">
        <!-- ============================================== -->
        <!-- STEP 1: Operator Selector, Display, Keypad     -->
        <!-- ============================================== -->
        <div v-if="step === 'input'" class="input-screen">
          <!-- Carrier Badges (Capsule Pill Style) -->
          <div class="carrier-pill-group">
            <button
              type="button"
              class="carrier-capsule mtn"
              :class="{ active: selectedOperator === 'mtn' }"
              @click="selectedOperator = 'mtn'"
            >
              <span class="carrier-dot"></span>
              <span class="carrier-title">MTN MoMo</span>
            </button>

            <button
              type="button"
              class="carrier-capsule airtel"
              :class="{ active: selectedOperator === 'airtel' }"
              @click="selectedOperator = 'airtel'"
            >
              <span class="carrier-dot"></span>
              <span class="carrier-title">Airtel Money</span>
            </button>

            <button
              type="button"
              class="carrier-capsule zamtel"
              :class="{ active: selectedOperator === 'zamtel' }"
              @click="selectedOperator = 'zamtel'"
            >
              <span class="carrier-dot"></span>
              <span class="carrier-title">Zamtel Kwacha</span>
            </button>
          </div>

          <!-- Phone Number Screen -->
          <div class="phone-display-capsule card-bento">
            <span class="phone-prefix font-data-mono">+260</span>
            <input
              type="text"
              readonly
              :value="formattedPhone"
              placeholder="097 / 096 / 095..."
              class="phone-readout font-data-mono"
            />
            <span v-if="detectedCarrierName" class="badge-pill auto-detected-pill" :class="detectedCarrierName">
              {{ detectedCarrierName.toUpperCase() }}
            </span>
          </div>

          <!-- On-Screen Bento Keypad -->
          <div class="bento-keypad-grid">
            <button
              v-for="digit in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '⌫']"
              :key="digit"
              class="keypad-tile card-bento"
              :class="{ 'key-special': digit === 'C' || digit === '⌫' }"
              @click="handleKeyPress(digit)"
            >
              {{ digit }}
            </button>
          </div>

          <div v-if="errorMessage" class="badge-pill badge-pill-red error-pill">
            <AlertCircle :size="13" :stroke-width="2.5" />
            <span>{{ errorMessage }}</span>
          </div>

          <!-- Primary Dispatch Button -->
          <button
            class="btn-pill-primary dispatch-btn"
            :disabled="isSubmitting || rawDigits.length < 9"
            @click="handleInitiate"
          >
            <Send :size="15" :stroke-width="2.2" />
            <span v-if="isSubmitting">Sending prompt to Lenco...</span>
            <span v-else>Dispatch USSD Push Prompt</span>
          </button>
        </div>

        <!-- ============================================== -->
        <!-- STEP 2: Waiting for Customer PIN                -->
        <!-- ============================================== -->
        <div v-else-if="step === 'waiting'" class="waiting-screen">
          <div class="pulse-beacon">
            <div class="beacon-circle">
              <Radio class="pulse-icon" :size="24" :stroke-width="2.2" />
            </div>
          </div>

          <div class="waiting-text">
            <h4>Customer PIN Prompt Dispatched</h4>
            <p>
              A prompt was sent to <strong>+260 {{ rawDigits }}</strong> via
              <strong>{{ selectedOperator.toUpperCase() }}</strong>.
            </p>
            <div class="badge-pill badge-pill-charcoal ref-pill font-data-mono">
              Ref: {{ lencoReference }}
            </div>
          </div>

          <!-- Developer Simulator Sandbox -->
          <div class="dev-box card-bento">
            <div class="dev-top">
              <span class="dev-headline">
                <Terminal :size="13" :stroke-width="2.2" />
                Local Lenco Simulator
              </span>
              <span class="badge-pill badge-pill-ochre">Mock Webhook</span>
            </div>
            <p class="dev-caption">Simulate customer entering PIN or declining prompt on their phone:</p>
            <div class="dev-buttons">
              <button
                class="btn-pill-primary dev-success-btn"
                :disabled="isSimulating"
                @click="simulateWebhook('successful')"
              >
                <Check :size="13" :stroke-width="2.5" />
                <span>Simulate PIN Approved</span>
              </button>
              <button
                class="btn-pill-outline dev-fail-btn"
                :disabled="isSimulating"
                @click="simulateWebhook('failed')"
              >
                <X :size="13" :stroke-width="2.5" />
                <span>Simulate Cancel</span>
              </button>
            </div>
          </div>
        </div>

        <!-- ============================================== -->
        <!-- STEP 3: Payment Confirmed (ZRA Fiscalized)     -->
        <!-- ============================================== -->
        <div v-else-if="step === 'success'" class="result-screen">
          <div class="success-icon-badge">
            <CheckCircle2 :size="28" :stroke-width="2.5" />
          </div>
          <h4>{{ isOfflineQueued ? 'Mobile Money Ticket Queued' : 'Payment Confirmed!' }}</h4>
          <p class="result-text">
            {{ isOfflineQueued
               ? 'Ticket saved into offline queue. USSD prompt will sync to Lenco gateway once internet returns.'
               : 'Settlement captured in Lenco Sub-account. Beverage crate stock decremented.' }}
          </p>

          <div v-if="isOfflineQueued" class="offline-momo-pill-row">
            <span class="badge-pill badge-pill-ochre font-data-mono">
              ⚡ Saved offline. Will sync when online.
            </span>
          </div>

          <div class="fiscal-receipt-box card-bento">
            <div class="receipt-line">
              <span>{{ isOfflineQueued ? 'Offline Ticket ID:' : 'Lenco Reference:' }}</span>
              <strong class="font-data-mono">{{ lencoReference }}</strong>
            </div>
            <div class="receipt-line">
              <span>Carrier Network:</span>
              <strong class="font-data-mono">{{ selectedOperator.toUpperCase() }}</strong>
            </div>
            <div class="receipt-line total">
              <span>Gross Settle:</span>
              <strong class="font-data-mono text-emerald">K{{ totalAmount.toFixed(2) }}</strong>
            </div>
          </div>

          <button class="btn-pill-primary finish-btn" @click="handleDone">
            <span>Complete & Next Order</span>
            <ArrowRight :size="15" :stroke-width="2.2" />
          </button>
        </div>

        <!-- ============================================== -->
        <!-- STEP 4: Payment Failed / Cancelled             -->
        <!-- ============================================== -->
        <div v-else-if="step === 'failed'" class="result-screen">
          <div class="fail-icon-badge">
            <AlertTriangle :size="28" :stroke-width="2.5" />
          </div>
          <h4>Payment Timed Out or Cancelled</h4>
          <p class="result-text">
            The customer did not authorize the prompt. Stock has not been deducted.
          </p>

          <div class="fail-button-row">
            <button class="btn-pill-primary retry-btn" @click="step = 'input'">
              <RefreshCw :size="14" :stroke-width="2.2" />
              <span>Retry Tender</span>
            </button>
            <button class="btn-pill-outline cancel-btn" @click="$emit('close')">
              Cancel Order
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue';
import {
  Smartphone,
  X,
  Send,
  AlertCircle,
  Radio,
  Terminal,
  Check,
  CheckCircle2,
  ArrowRight,
  AlertTriangle,
  RefreshCw,
} from 'lucide-vue-next';
import { api } from '../services/api.js';
import { authState } from '../stores/auth.js';
import { cartState } from '../stores/cart.js';
import { offlineQueue } from '../stores/offlineQueue.js';

const props = defineProps({
  totalAmount: {
    type: Number,
    required: true,
  },
});

const emit = defineEmits(['close', 'order-completed']);

const step = ref('input'); // 'input', 'waiting', 'success', 'failed'
const selectedOperator = ref('airtel');
const rawDigits = ref('0977123456');
const isSubmitting = ref(false);
const isSimulating = ref(false);
const isOfflineQueued = ref(false);
const errorMessage = ref('');
const lencoReference = ref('');
let pollInterval = null;

const formattedPhone = computed(() => rawDigits.value);

const detectedCarrierName = computed(() => {
  const d = rawDigits.value;
  if (d.startsWith('096') || d.startsWith('076') || d.startsWith('96') || d.startsWith('76')) return 'mtn';
  if (d.startsWith('097') || d.startsWith('077') || d.startsWith('97') || d.startsWith('77')) return 'airtel';
  if (d.startsWith('095') || d.startsWith('075') || d.startsWith('95') || d.startsWith('75')) return 'zamtel';
  return null;
});

watch(detectedCarrierName, (newCarrier) => {
  if (newCarrier) {
    selectedOperator.value = newCarrier;
  }
});

const handleKeyPress = (digit) => {
  errorMessage.value = '';
  if (digit === 'C') {
    rawDigits.value = '';
  } else if (digit === '⌫') {
    rawDigits.value = rawDigits.value.slice(0, -1);
  } else {
    if (rawDigits.value.length < 10) {
      rawDigits.value += digit;
    }
  }
};

const stopPolling = () => {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
};

onUnmounted(() => {
  stopPolling();
});

const handleInitiate = async () => {
  if (!rawDigits.value) return;
  isSubmitting.value = true;
  errorMessage.value = '';

  try {
    const orderPayload = {
      payment_method: 'mobile_money',
      items: cartState.items.map((i) => ({
        menu_item_id: i.id,
        quantity: i.quantity,
      })),
    };

    if (!offlineQueue.effectiveOnline) {
      const orderRes = await api.createOrder(orderPayload, cartState.items);
      lencoReference.value = orderRes.id;
      isOfflineQueued.value = true;
      step.value = 'success';
      return;
    }

    const orderRes = await api.createOrder(orderPayload, cartState.items);
    const orderId = orderRes.id;

    const initRes = await api.initiateMobileMoney(
      orderId,
      rawDigits.value,
      selectedOperator.value
    );

    lencoReference.value = initRes.lenco_reference;
    step.value = 'waiting';
    startPolling(lencoReference.value);
  } catch (err) {
    errorMessage.value = err.message || 'Failed to dispatch mobile money push prompt';
  } finally {
    isSubmitting.value = false;
  }
};

const startPolling = (refString) => {
  stopPolling();
  pollInterval = setInterval(async () => {
    try {
      const statusRes = await api.pollPaymentStatus(refString);
      if (statusRes.payment_status === 'paid') {
        stopPolling();
        step.value = 'success';
      } else if (statusRes.payment_status === 'failed') {
        stopPolling();
        step.value = 'failed';
      }
    } catch (e) {
      console.warn('Polling error:', e);
    }
  }, 1500);
};

const simulateWebhook = async (status) => {
  if (!lencoReference.value) return;
  isSimulating.value = true;
  try {
    await api.simulateLencoWebhook(lencoReference.value, status);
  } catch (err) {
    console.error('Webhook simulation error:', err);
  } finally {
    isSimulating.value = false;
  }
};

const handleDone = () => {
  cartState.clearCart();
  emit('order-completed');
  emit('close');
};
</script>

<style scoped>
.momo-bento-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(8, 37, 21, 0.65);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
  padding: 16px;
}

.momo-bento-card {
  width: 100%;
  max-width: 480px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* Header (Hero Inversion #0B2416) */
.momo-header-hero {
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hero-header-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.momo-emblem {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background-color: var(--color-primary-accent);
  color: var(--color-on-primary-container);
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-titles h3 {
  font-size: 16px;
  font-weight: 700;
  color: #FFFFFF;
}

.hero-titles p {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.65);
}

.hero-close-btn {
  background: rgba(255, 255, 255, 0.1);
  border: none;
  color: #FFFFFF;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Amount Strip */
.amount-strip {
  margin: 14px 16px 0;
  padding: 12px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: var(--color-surface-dim);
}

.strip-labels {
  display: flex;
  flex-direction: column;
}

.label-caption {
  font-size: 10px;
  font-weight: 700;
  color: var(--color-primary);
  letter-spacing: 0.05em;
}

.label-sub {
  font-size: 10px;
  color: var(--color-on-surface-variant);
}

.strip-val {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-on-surface);
}

/* Body Area */
.momo-body-area {
  padding: 16px;
}

/* Carrier Group */
.carrier-pill-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.carrier-capsule {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-pill);
  background-color: var(--color-surface-dim);
  border: 1px solid var(--color-border-card);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-on-surface);
  cursor: pointer;
  transition: all 0.15s ease;
}

.carrier-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.carrier-capsule.mtn .carrier-dot { background-color: var(--color-mtn); }
.carrier-capsule.airtel .carrier-dot { background-color: var(--color-airtel); }
.carrier-capsule.zamtel .carrier-dot { background-color: var(--color-zamtel); }

.carrier-capsule.active {
  background-color: var(--color-surface);
  border-color: var(--color-primary);
  box-shadow: 0 2px 8px rgba(12, 26, 18, 0.08);
}

/* Phone Screen */
.phone-display-capsule {
  display: flex;
  align-items: center;
  padding: 0 16px;
  height: 48px;
  border-radius: var(--radius-pill);
  gap: 8px;
  margin-bottom: 14px;
}

.phone-prefix {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-primary);
}

.phone-readout {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 18px;
  font-weight: 700;
  color: var(--color-on-surface);
  letter-spacing: 0.05em;
}

.auto-detected-pill {
  font-size: 9px;
  padding: 2px 8px;
}

.auto-detected-pill.mtn { background-color: #FEF3C7; color: #92400E; }
.auto-detected-pill.airtel { background-color: #FEE2E2; color: #991B1B; }
.auto-detected-pill.zamtel { background-color: #DCFCE7; color: #166534; }

/* Bento Keypad */
.bento-keypad-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.keypad-tile {
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-data-mono);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-on-surface);
  cursor: pointer;
  border-radius: var(--radius-subtle);
  border: 1px solid var(--color-border-card);
}

.keypad-tile:hover {
  background-color: var(--color-surface-dim);
  border-color: var(--color-primary-accent);
}

.keypad-tile.key-special {
  color: var(--color-error);
  font-size: 15px;
}

.error-pill {
  width: 100%;
  justify-content: center;
  margin-bottom: 10px;
}

.dispatch-btn {
  width: 100%;
  height: 48px;
}

/* Waiting Screen */
.waiting-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 14px;
  padding: 10px 0;
}

.pulse-beacon {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  background-color: var(--color-primary-container);
  display: flex;
  align-items: center;
  justify-content: center;
}

.pulse-icon {
  color: var(--color-primary);
  animation: pulse 1.5s infinite alternate;
}

@keyframes pulse {
  to { opacity: 0.4; transform: scale(0.9); }
}

.waiting-text h4 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-on-surface);
}

.waiting-text p {
  font-size: 12px;
  color: var(--color-on-surface-variant);
  margin-top: 4px;
}

.ref-pill {
  margin-top: 8px;
  display: inline-block;
}

.dev-box {
  width: 100%;
  padding: 12px 14px;
  background-color: var(--color-surface-dim);
  text-align: left;
}

.dev-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dev-headline {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-tertiary);
}

.dev-caption {
  font-size: 10px;
  color: var(--color-on-surface-variant);
  margin: 4px 0 8px;
}

.dev-buttons {
  display: flex;
  gap: 8px;
}

.dev-success-btn {
  flex: 1;
  padding: 8px;
  font-size: 11px;
  background-color: var(--color-primary-accent);
  color: var(--color-on-primary-container);
}

.dev-fail-btn {
  flex: 1;
  padding: 8px;
  font-size: 11px;
}

/* Results Screens */
.result-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12px;
  padding: 12px 0;
}

.success-icon-badge {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background-color: var(--color-primary-container);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.fail-icon-badge {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background-color: var(--color-error-container);
  color: var(--color-error);
  display: flex;
  align-items: center;
  justify-content: center;
}

.result-text {
  font-size: 12px;
  color: var(--color-on-surface-variant);
  max-width: 320px;
}

.offline-momo-pill-row {
  margin: 4px 0 6px;
  display: flex;
  justify-content: center;
}

.fiscal-receipt-box {
  width: 100%;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  font-size: 12px;
  background-color: var(--color-surface-dim);
}

.receipt-line {
  display: flex;
  justify-content: space-between;
  color: var(--color-on-surface-variant);
}

.receipt-line.total {
  border-top: 1px solid var(--color-border-card);
  padding-top: 6px;
  font-size: 14px;
}

.text-emerald {
  color: var(--color-primary);
  font-size: 16px;
}

.finish-btn {
  width: 100%;
  height: 46px;
}

.fail-button-row {
  display: flex;
  width: 100%;
  gap: 8px;
}

.retry-btn {
  flex: 1;
  height: 44px;
}

.cancel-btn {
  flex: 1;
  height: 44px;
}
</style>
