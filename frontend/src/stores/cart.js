import { reactive, computed } from 'vue';

export const cartState = reactive({
  items: [], // [{ id, name, category, price_zmw, quantity, max_stock }]
  tableNumber: 'Table 04',
  orderNumber: '0142',
  serviceChargeEnabled: false,

  addItem(menuItem) {
    const existing = cartState.items.find((i) => i.id === menuItem.id);
    const maxStock = menuItem.drink_inventory ? menuItem.drink_inventory.stock_quantity : Infinity;

    if (existing) {
      if (existing.quantity < maxStock) {
        existing.quantity += 1;
      }
    } else {
      if (maxStock > 0) {
        cartState.items.push({
          id: menuItem.id,
          name: menuItem.name,
          category: menuItem.category,
          price_zmw: menuItem.price_zmw,
          quantity: 1,
          max_stock: maxStock,
        });
      }
    }
  },

  increaseQty(itemId) {
    const item = cartState.items.find((i) => i.id === itemId);
    if (item && item.quantity < item.max_stock) {
      item.quantity += 1;
    }
  },

  decreaseQty(itemId) {
    const index = cartState.items.findIndex((i) => i.id === itemId);
    if (index !== -1) {
      if (cartState.items[index].quantity > 1) {
        cartState.items[index].quantity -= 1;
      } else {
        cartState.items.splice(index, 1);
      }
    }
  },

  removeItem(itemId) {
    const index = cartState.items.findIndex((i) => i.id === itemId);
    if (index !== -1) {
      cartState.items.splice(index, 1);
    }
  },

  clearCart() {
    cartState.items = [];
    // Cycle ticket number
    const nextNum = Math.floor(Math.random() * 800) + 100;
    cartState.orderNumber = String(nextNum).padStart(4, '0');
  },

  subtotalAmount: computed(() =>
    cartState.items.reduce((sum, item) => sum + item.price_zmw * item.quantity, 0)
  ),

  // ZRA 16% VAT standard calculation (inclusive breakdown)
  vatAmount: computed(() => {
    // 16% VAT included in menu pricing: Tax = Total - (Total / 1.16)
    const sub = cartState.subtotalAmount;
    return sub > 0 ? (sub * 0.16) / 1.16 : 0;
  }),

  serviceChargeAmount: computed(() => {
    return cartState.serviceChargeEnabled ? cartState.subtotalAmount * 0.05 : 0;
  }),

  totalAmount: computed(() => {
    return cartState.subtotalAmount + cartState.serviceChargeAmount;
  }),

  totalCount: computed(() =>
    cartState.items.reduce((sum, item) => sum + item.quantity, 0)
  ),
});
