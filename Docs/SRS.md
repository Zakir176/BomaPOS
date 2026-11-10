# BomaPOS: Lightweight Restaurant POS & Mobile Money Platform

**Software Requirements Specification (SRS) — Phase 1 Prototype**

**Prepared for:** Aunt’s Restaurant, Lusaka, Zambia

**Author:** Zakir Motala

**Document Version:** 2.0 | September 2026

---

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification (SRS) defines the functional and non-functional requirements for BomaPOS, a lightweight Point of Sale (POS) and Mobile Money Integration System. It provides a shared, accurate reference for what will be built, ensuring clear development tracking for a cost-effective digital solution tailored for a local restaurant in Lusaka, Zambia.

### 1.2 Scope

BomaPOS replaces manual paper-based record-keeping with a digital interface that captures sales, manages drink inventory, tracks daily revenue, and routes mobile money transactions directly into a business sub-account via the Lenco API, eliminating high intermediary agent withdrawal fees. The system incorporates Role-Based Access Control (Staff vs. Owner views) and Offline-First PWA Caching to withstand local network instability. The long-term vision includes raw ingredient recipe tracking, expense logs, customer credit tabs, and dynamic QR code generation.

### 1.3 Intended Audience

* **Zakir Motala** — Lead Developer & System Architect
* **Restaurant Owner (Aunt)** — Primary Business Stakeholder & Administrator
* **Restaurant Staff / Cashiers** — Daily Operational Users

### 1.4 Project Scope: In / Out for Phase 1

| Capability | Phase 1 Status | Notes |
| --- | --- | --- |
| **POS Order & Cart Entry** | Fully built | Vue 3 SPA interface with real-time cart computation |
| **Role-Based Access Control** | Fully built | Strict separation between Cashier and Owner views |
| **Mobile Money Collections** | Fully built | Integrated via Lenco API (MTN, Airtel, Zamtel) |
| **Drink Inventory Tracking** | Fully built | Strict whole-unit inventory tracking with low-stock alerts |
| **Revenue & Settlement Dashboards** | Fully built | Real-time tracking of daily revenue and sub-account status |
| **Offline-First PWA Caching** | Fully built | Local storage queue via Service Workers / IndexedDB |
| **Raw Ingredient Recipe Mapping** | Out of scope | Pushed to Phase 2 / V2 expansion |
| **Expense & Petty Cash Logs** | Out of scope | Pushed to Phase 2 / V2 expansion |

### 1.5 Definitions, Acronyms, Abbreviations

| Term | Definition |
| --- | --- |
| **SRS** | Software Requirements Specification |
| **POS** | Point of Sale |
| **PWA** | Progressive Web App |
| **API** | Application Programming Interface |
| **CRUD** | Create, Read, Update, Delete |
| **ZMW** | Zambian Kwacha (Currency) |

### 1.6 References

* Lenco API Developer Documentation (Mobile Money Collections & Sub-accounts)
* Supabase Documentation (PostgreSQL Cloud Database)
* Vue.js 3 & FastAPI Architecture Standards

---

## 2. Overall Description

### 2.1 Product Perspective

BomaPOS is a cloud-hosted web application comprising a Vue.js single-page frontend (structured as a Progressive Web App), a Python FastAPI backend service, and a PostgreSQL database hosted on Supabase. It integrates externally with the Lenco payment gateway to handle multi-network mobile money collections. It is built as a greenfield application with no legacy database dependencies.

### 2.2 Product Functions (Summary)

* Process customer orders and calculate cart totals via a streamlined touch-friendly interface.
* Execute direct mobile money push payments via Lenco, routing funds directly to a business sub-account.
* Enforce role-based security separating cashier order entry from owner financial controls.
* Track strict whole-unit drink inventory and trigger low-stock alerts automatically.
* Maintain operational continuity during unstable network conditions via offline-first PWA caching.

### 2.3 User Classes and Characteristics

| User Class | Description | Technical Skill |
| --- | --- | --- |
| **Cashier / Staff** | Enters orders, manages cart items, processes cash/mobile money payments. | Low — requires an intuitive UI |
| **Restaurant Owner (Aunt)** | Views daily revenue, audits settlement accounts, checks drink stock thresholds. | Low to Moderate |
| **Developer (Zakir Motala)** | Builds, deploys, maintains code architecture, and configures APIs. | High |

### 2.4 Operating Environment

* **Frontend:** Modern web browsers (Chrome, Edge, Safari) running on Android tablets or desktop/mobile devices.
* **Backend:** FastAPI (Python 3.11+), deployed on Render.
* **Database:** PostgreSQL (hosted on Supabase).
* **Hosting Platforms:** Vercel (Frontend PWA) and Render (Backend API).

### 2.5 Design and Implementation Constraints

* Single-developer development cycle working alongside academic commitments.
* Must maintain strict cost-efficiency, utilizing free-tier cloud quotas for Supabase, Vercel, and Render during early operations.
* Must operate reliably under standard Zambian mobile network conditions, necessitating robust offline caching capabilities.

### 2.6 Assumptions and Dependencies

* Stable internet access or intermittent cellular data will be available at the restaurant location for web synchronization.
* Lenco API sandbox and production credentials remain active and accessible.
* The device used at the counter supports modern browser PWA installation and local storage execution.

### 2.7 Project Schedule Context

Development proceeds from initial UI mockups through local mock integration, Lenco API integration, and final cloud deployment.

---

## 3. Functional Requirements

*(Priority: Must = required for core system operation; Should = high-value addition included in Phase 1)*

### 3.1 User Authentication & Role Management

* **FR-1.1 (Must):** The system shall authenticate users and assign roles based on credentials (Cashier vs. Owner).
* **FR-1.2 (Must):** The Cashier role shall restrict access strictly to order entry, cart processing, and payment triggers.
* **FR-1.3 (Must):** The Owner role shall grant access to financial dashboards, inventory thresholds, and administrative settings.

### 3.2 POS Order & Checkout

* **FR-2.1 (Must):** The system shall display a grid/list interface of menu items categorized for fast selection.
* **FR-2.2 (Must):** The system shall allow staff to add, remove, and update item quantities in an active order cart.
* **FR-2.3 (Must):** The system shall calculate sub-totals and grand totals dynamically upon cart modification.
* **FR-2.4 (Must):** The system shall support payment checkout via Cash or Mobile Money.

### 3.3 Mobile Money Integration (via Lenco)

* **FR-3.1 (Must):** The system shall allow the user to input the customer's phone number and select network operator (MTN, Airtel, Zamtel).
* **FR-3.2 (Must):** The backend shall send a collection request to the Lenco API to trigger a USSD push prompt on the customer's phone.
* **FR-3.3 (Must):** The backend shall listen for incoming webhook notifications from Lenco to confirm transaction success.
* **FR-3.4 (Must):** The system shall automatically update order status to "Paid" upon receiving a successful payment webhook.

### 3.4 Drink Inventory Tracking & Low-Stock Alerts

* **FR-4.1 (Must):** The system shall track whole-unit inventory counts for beverages (crates and bottles).
* **FR-4.2 (Must):** The system shall automatically decrement drink stock quantities upon completion of an order.
* **FR-4.3 (Should):** The system shall generate a visual alert when a drink item falls below a predefined low-stock threshold.

### 3.5 Analytics, Calendars & Revenue Dashboards

* **FR-5.1 (Must):** The system shall display a real-time dashboard showing today's total accumulated revenue.
* **FR-5.2 (Must):** The system shall display settlement account balance tracking reflecting Lenco mobile money transactions.
* **FR-5.3 (Should):** The system shall provide a visual calendar/history view showing sales summaries per day.

### 3.6 Offline-First PWA Synchronization

* **FR-6.1 (Should):** The PWA frontend shall cache core assets locally to operate during intermittent network drops.
* **FR-6.2 (Should):** The system shall queue offline orders locally in browser storage and auto-sync to Supabase once connectivity is restored.

---

## 4. Non-Functional Requirements

### 4.1 Performance

* Core dashboard and order pages shall load within 3 seconds under normal broadband or 4G mobile conditions.
* UI touch response times shall remain immediate to prevent cashier bottlenecks during peak service hours.

### 4.2 Usability

* The interface shall feature clear, large touch targets suitable for restaurant cashiers operating on tablets or touch screens.
* Navigation between sales, inventory, and dashboards shall require minimal training.

### 4.3 Reliability

* Core database persistence and local offline caching shall guarantee zero data loss during temporary local network outages.
* The system shall gracefully handle API timeout responses from payment providers without crashing the POS session.

### 4.4 Security

* Authentication tokens shall secure communication between the Vue.js frontend and FastAPI backend.
* All data in transit shall enforce secure HTTPS encryption.
* API secret keys (Lenco, Supabase) shall be stored securely as environment variables on the Render backend and never exposed on the client frontend.

### 4.5 Maintainability

* Code architecture shall cleanly separate frontend UI components, backend routing logic, and database interactions to ease future feature expansions.

### 4.6 Portability

* The application shall be accessible via any modern web browser or installed as a Progressive Web App (PWA) on Android tablets or desktop terminals without OS-specific native installations.

---

## Appendix A: Open Dependency Tracker

| Item | Needed By | Status |
| --- | --- | --- |
| **Lenco Merchant Sub-account Credentials** | Integration Phase | Pending |
| **Menu Item Pricing & Drink Stock Baseline Data** | UI Mockup Phase | Pending |
| **Target Tablet Device Verification for PWA / Testing** | Deployment Phase | Pending |
