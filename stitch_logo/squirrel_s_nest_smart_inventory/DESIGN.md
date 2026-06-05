---
name: Squirrel's Nest Smart Inventory
colors:
  surface: '#fcf9f8'
  surface-dim: '#dcd9d9'
  surface-bright: '#fcf9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f2'
  surface-container: '#f0eded'
  surface-container-high: '#eae7e7'
  surface-container-highest: '#e5e2e1'
  on-surface: '#1b1c1c'
  on-surface-variant: '#5a4045'
  inverse-surface: '#303030'
  inverse-on-surface: '#f3f0ef'
  outline: '#8e6f75'
  outline-variant: '#e2bdc3'
  surface-tint: '#bb0054'
  primary: '#b70052'
  on-primary: '#ffffff'
  primary-container: '#dd2269'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb1c1'
  secondary: '#006e1c'
  on-secondary: '#ffffff'
  secondary-container: '#91f78e'
  on-secondary-container: '#00731e'
  tertiary: '#695f00'
  on-tertiary: '#ffffff'
  tertiary-container: '#bdad00'
  on-tertiary-container: '#474000'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffd9df'
  primary-fixed-dim: '#ffb1c1'
  on-primary-fixed: '#3f0018'
  on-primary-fixed-variant: '#8f003f'
  secondary-fixed: '#94f990'
  secondary-fixed-dim: '#78dc77'
  on-secondary-fixed: '#002204'
  on-secondary-fixed-variant: '#005313'
  tertiary-fixed: '#f9e534'
  tertiary-fixed-dim: '#dbc90a'
  on-tertiary-fixed: '#201c00'
  on-tertiary-fixed-variant: '#4f4800'
  background: '#fcf9f8'
  on-background: '#1b1c1c'
  surface-variant: '#e5e2e1'
typography:
  display-lg:
    fontFamily: Bricolage Grotesque
    fontSize: 48px
    fontWeight: '800'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Bricolage Grotesque
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
  headline-lg-mobile:
    fontFamily: Bricolage Grotesque
    fontSize: 28px
    fontWeight: '700'
    lineHeight: '1.2'
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '500'
    lineHeight: '1.6'
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  label-bold:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '700'
    lineHeight: '1.2'
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  unit: 8px
  gutter: 16px
  margin-mobile: 20px
  margin-desktop: 40px
  stroke-weight: 2px
---

## Brand & Style

The design system is built on a "Doodle-Core" aesthetic, drawing inspiration from the expressive, high-energy illustrations of Al Murphy. It transforms the mundane task of inventory management into a playful, creative activity. The brand personality is industrious yet whimsical—imagine a squirrel who is highly organized but also loves to draw in the margins of their ledger.

The visual style leans into **Bold Illustrative Minimalism**. It utilizes heavy black outlines, irregular "hand-drawn" containers, and a vibrant, saturated color palette set against warm, papery backgrounds. The goal is to evoke a sense of tactile joy and accessibility, making "home organization" feel like "home play."

## Colors

The palette is anchored by a warm, buttery background (`#FFF9C4`) that mimics the feel of a physical notepad. Vibrant neon accents provide energetic contrast for interaction points.

- **Primary (Pink):** Used for main actions, squirrel branding, and high-energy highlights.
- **Secondary (Green):** Used for "In Stock" status, growth, and confirmation.
- **Tertiary (Yellow):** Used for category badges and secondary interactive elements.
- **Neutrals:** A "Rich Black" (`#212121`) is used for all outlines and text to maintain the hand-inked feel.
- **Functional Borders:** Specific status-coded borders (Red, Yellow, Gray) are used on cards to denote inventory levels (Out of stock, Low stock, Full).

## Typography

The typography strategy pairs a "wonky" display face with a highly legible, friendly sans-serif for functional data.

- **Headlines:** Use **Bricolage Grotesque**. Its variable, slightly eccentric terminals mimic hand-cut lettering. It should be used for all Chinese and English headings.
- **Body & UI:** **Plus Jakarta Sans** provides a clean, soft, and modern contrast. It ensures that item names and quantities remain readable at a glance.
- **Stylistic Note:** Headings should occasionally be placed inside "blob" containers (hand-drawn circles or capsules) with a 2px black stroke to reinforce the Al Murphy aesthetic.

## Layout & Spacing

This design system uses a **Fluid-Fixed Hybrid** grid. While the grid is mathematically sound, the visual application should feel slightly "off-center."

- **The 2px Rule:** Every major container (cards, buttons, inputs) must have a consistent 2px solid black border.
- **Safe Margins:** Use generous padding within cards (24px) to let the "hand-drawn" icons breathe.
- **Rhythm:** Elements should not be perfectly aligned to a strict grid; use subtle 1-2 degree rotations on cards or badges to simulate stickers on a surface.
- **Mobile:** A single-column vertical stack for inventory items with full-width action buttons at the bottom.

## Elevation & Depth

In this design system, depth is communicated through **Graphic Shadows** rather than realistic blurs.

- **The Offset Shadow:** Instead of a soft Gaussian blur, use a "Hard Shadow"—a solid black or dark-tinted fill offset by 4px to the bottom-right.
- **Layering:** Items "lift" when interacted with by increasing the offset of the hard shadow, making them appear to pop off the yellow background.
- **Stroke Depth:** Overlapping elements should always be separated by the 2px black outline to maintain clarity.

## Shapes

The shape language is dominated by **Exaggerated Rounds**.

- **Pill Shapes:** Every button and input field should use a maximum corner radius, creating a "pill" or "sausage" look.
- **Irregular Blobs:** For decorative background elements or category badges, use non-perfect circles that look like they were drawn with a thick marker in one stroke.
- **Card Radius:** Standard cards use `rounded-xl` (1.5rem/24px) to feel soft and approachable.

## Components

### Buttons & Inputs
Buttons are "pill-shaped" with a 2px black outline and a solid fill of Pink or Yellow. Upon hover/press, the button should shift 2px down and right, "covering" its own hard shadow. Input fields should have a white background, the 2px stroke, and use **Plus Jakarta Sans** for entry.

### Inventory Cards
Cards represent items. They feature:
- A 2px black outline.
- A status-colored secondary border (Red for empty, Yellow for low).
- A chunky, hand-drawn icon of the item (e.g., a simple sketch of a box, a spoon, or a tool).
- A "Hard Shadow" offset.

### Chips & Badges
Small capsules used for categories (e.g., "Kitchen," "Garage"). These should use the Tertiary Yellow or Secondary Green with bold black text.

### Iconography
Icons must never be thin or clinical. Use a "chunky marker" style—heavy strokes, closed loops, and slightly imperfect symmetry. They should look like they were drawn by the same hand that wrote the headings.

### List Items
For dense data, use simple rows separated by a 2px horizontal black line, with a "hand-drawn" checkbox (a simple square with a thick 'X' when active).