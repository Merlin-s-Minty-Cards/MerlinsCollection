# **Database & Interface Enhancements**

Your goal is to improve and build out the following functional modules. We are using a TDD approach; please draft your test plans before implementation.

# **1\. Advanced Trade & Transaction Engine**

**The Issue:** The current system does not account for complex trades involving cash/Venmo, or the nuances of "Vendor-to-Vendor" trades where margins need to be split.

**What "Done" Looks Like:**

* **Multi-Asset Input:** The trade interface allows for any combination of "Cards In," "Cards Out," "Cash/Venmo/zelle/card In," and "Cash/Venmo/zelle/card Out".  
* **Cost Basis Logic:** By default, the system ensures the total value of "Cards In" equals the cost basis of "Cards Out" (plus any cash paid/received).  
* **Vendor Trade Override:** For vendor-to-vendor trades, a "Margin Split" feature allows the user to manually confirm a percentage of profit on the trade and adjust the incoming card's cost basis accordingly.

# **2\. Visual Buy/Sell Workflows**

**The Issue:** Inventory errors (wrong card, wrong language) occur because the staff can't visually verify items during high-speed transactions.

**What "Done" Looks Like:**

* **Image Confirmation:** Both the "Buy" and "Sell" tools automatically pull and display high-resolution card images when an item is selected to ensure the physical card matches the digital record. These images should be large enough to see  
* **Dedicated Flows:** While functionally similar, there are two distinct interfaces: one optimized for purchasing new inventory (Acquisition) and one for customer sales (Liquidation). Both the buy and sell tools should have the image confirmation feature as described above.

# **3\. Show Prep & Market Intelligence Dashboard**

**The Issue:** Updating sticker prices for card shows is currently a manual, slow process.

**What "Done" Looks Like:**

* **Live Market Links:** The interface provides a TCGplayer link for each flagged card for instant verification. Evaluate whether it would be safer to have it be a link to the search results page or a link to the actual card page.  
* **Bulk Location Updates:** A tool that allows staff to select multiple items and update their digital "Location" (e.g., moving a stack of cards from "Main Inventory" to "Show Box A") simultaneously. The option to move location should be a dropdown menu with different options  
* **Trend Sorting:** The ability to sort inventory by "Market Delta" (highest value drop vs. highest value gain).  
* **Sticker Updating:** The ability to quickly update the stickers of cards through the use of a text box, like the way users are currently able to add a TCG link on the show prep page

# **4\. Cosigner & Administration Management**

**The Issue:** We need a way to track inventory that we do not own outright and ensure accurate payout reporting.

**What "Done" Looks Like:**

* **Cosigner Profiles:** An administration interface to create cosigners with specific contact info and a designated "Payout %".  
* **Asset Association:** A tool to link specific Card IDs to a cosigner profile.  
* **Filtered Analytics:** All search and lookup tools must clearly identify if a card is "Owned" or "Cosigned".

# **5\. Enhanced Inventory Lookup**

**The Issue:** Search is currently too restrictive.

**What "Done" Looks Like:**

* **Granular Filters:** Staff can filter the entire database by:  
  * Card Name & Set.  
  * Card Number.  
  * Artist Name.  
  * Price Range.  
  * Physical Location.  
* **Confidence Ratings:** For the "Market Lookup" tool, provide a confidence rating for potential purchases based on historical market trends.

# **6\. Transaction History & Inventory Growth Tracking**

**The Issue:**  
Once a card has been traded multiple times, there is currently no way to view its complete transaction history or measure how much value the business generated throughout its lifecycle.

**What "Done" Looks Like:**

* **A separate tab labed transaction history:** This tab should have a search feature to find a card by name, price, lifetime profit generated etc.  
* **Complete Asset Timeline:** Every inventory item maintains a chronological history of every purchase, trade, and sale tied to its Inventory ID.  
* **Trade Progression Tracking:** Staff can see the complete evolution of an item. A card has completed its lifecycle of trade tracking when it is converted entirely into cash. Example:  
  * Start of trade life  
    * Purchased Card A for $15  
  * Middle of trade life  
    * Traded Card A (valued at $20) for Card B (valued at $25)  
  * Middle of trade life  
    * Traded card B (valued at $25) for Card C (valued at 25\) \+ Cash ($5)  
  * End of trade life  
    * Sold Card C for $25  
* **Profit Visibility:** The system displays realized profit at every step and cumulative profit generated across the entire trade chain.  
* **Linked Transactions:** Clicking any transaction displays the preceding and subsequent transactions associated with that inventory lineage.  
* **Historical Audit Trail:** Every valuation, trade adjustment, and ownership change remains permanently accessible for reporting and auditing.

# **7\. Outgoing Inventory Preparation Queue**

**The Issue:**  
Newly acquired inventory during shows need to be labeled with stickers before customers can see them, by not having a way to efficiently update stickers as cards are brought in this increases the manual work needed as well as the chance of pricing mistakes

**What "Done" Looks Like:**

* **Dedicated "Going Out" Queue:** A separate workflow displays all inventory that has not yet been assigned a sticker price.  
* **Visual Verification:** Every item includes a high-resolution card image for quick identification, these images should be loaded when the page is initially loaded  
* **Inline Sticker Pricing:** Staff can immediately assign sticker prices directly from the queue using a text input located next to the associated card.  
* **Inline Location:** Staff can immediately assign a location for the card directly from the queue using a text input located next to the associated card.  
* **Completion Workflow:** Once a sticker price is entered, the card is automatically removed from the queue and marked as show-ready.  
* **Bulk Pricing Support:** Staff can rapidly work through multiple cards without opening each inventory record individually.

# **8\. Daily Show Analytics & Transaction Dashboard**

**The Issue:**  
Current show reporting exists only as spreadsheet data, making it difficult to review historical performance, analyze individual shows, or revisit transactions completed during an event. This data will also no longer be accessible once we switch over to the website, so having a way to access this data will be very important for our operations.

**What "Done" Looks Like:**

* **Individual workflow page on the sidebar:** labeled show analytics  
* **Date-Based Dashboard:** Every business day or show date automatically generates its own reporting page.  
* **Transaction Archive:** All purchases, trades, and sales completed on that date are stored together for future reference.  
* **Show Performance Metrics:** The dashboard automatically calculates:  
  * Total Amount Sold  
  * Total Amount Bought  
  * Net Sales (Sold − Bought)  
  * Inventory Value Heading Into the Show  
  * Percentage of Inventory Sold  
* **Comprehensive Sold Total:** Includes both cash sales and the assigned value of inventory traded away.  
* **Comprehensive Bought Total:** Includes both cash purchases and the assigned value of inventory received through trades.  
* **Inventory Snapshot:** Inventory value is calculated using only inventory that existed prior to the start of the show, and should exclude items that were bought and sold on that date.  
* **Historical Reporting:** Staff can revisit any previous show date to review performance metrics and transaction history without relying on external spreadsheets.

# **9\. Enhanced Show Performance Metrics**

**The Issue:**  
Current reporting captures only basic totals and does not fully represent trading activity or inventory movement during events.

**What "Done" Looks Like:**

* **Expanded Sales Calculation:** "Total Sold" includes:  
  * Cash sales  
  * Trade-out valuations  
* **Expanded Purchase Calculation:** "Total Bought" includes:  
  * Cash purchases  
  * Trade-in valuations  
* **Automatic Net Calculation:** Net sales are automatically calculated as Total Sold minus Total Bought.  
* **Inventory Sell-Through Rate:** The system calculates the percentage of starting inventory sold during the event.  
* **Consistent Reporting Logic:** All metrics are standardized across shows, ensuring accurate comparisons between events and eliminating manual spreadsheet calculations.  
* **Placement:** This should all be bundled in with the Daily Show Analytics & Transaction Dashboard

# **10\. Card Details & Information Enhancements**

**The Issue:**  
Important card information is either difficult to access or inconsistently displayed, slowing staff during transactions and increasing the likelihood of errors.

**What "Done" Looks Like:**

* **Dedicated Link Section:** The Card Details page includes a dedicated **"Link"** section displaying the TCGplayer (or associated market) link assigned during Show Prep.  
* **Clickable Market Link:** The stored link is fully clickable, allowing staff to quickly open the listing in a new browser tab for price verification.  
* **Persistent Card Image:** The card image is always displayed in the upper-left corner of the Card Details page whenever an image is available.  
* **Reliable Image Loading:** Image loading is improved to eliminate cases where card images fail to appear despite existing in the database.

# **11\. Enhanced Buy Workflow**

**The Issue:**  
The current Buy interface lacks flexibility for entering historical or future transactions and requires unnecessary navigation while purchasing inventory.

**What "Done" Looks Like:**

* **Transaction Date Field:** The Buy page includes a transaction date selector located near the **Confirm Purchase** button.  
* **Automatic Date Population:** The date field defaults to the current date for normal purchases.  
* **Editable Transaction Date:** Staff can manually adjust the date to backdate or future-date purchases when necessary.  
* **Improved Layout:** The **Purchasing** column is repositioned to the left of the **Add Card** section, creating a more intuitive workflow and reducing unnecessary cursor movement during high-volume acquisitions.

# **12\. Visual Sales Workflow Improvements**

**The Issue:**  
Staff currently cannot visually verify selected inventory during customer sales, increasing the risk of selecting or selling the wrong card.

**What "Done" Looks Like:**

* **Image Preview During Sales:** Once a card is selected from inventory on the Sale page, its image is immediately displayed alongside the transaction details.  
* **Visual Verification:** Staff can quickly confirm the physical card matches the selected inventory record before completing the sale.

# **13\. Trade Calculator Layout Optimization**

**The Issue:**  
The current Trade Calculator layout does not follow the natural flow of incoming and outgoing assets, making trades more difficult to review.

**What "Done" Looks Like:**

* **Workflow Reorganization:** The **Coming In** section is moved to the left side of the Trade Calculator.  
* **Outgoing Assets on Right:** The **Going Out** section is positioned on the right side of the interface.  
* **Improved Transaction Flow:** The updated layout reflects the natural progression of receiving inventory before evaluating outgoing assets, improving readability and reducing user confusion during trades.

# **14\. Interface & Data Integrity Enhancements**

**The Issue:**  
Current visual and input methods are causing user friction, data errors, and inventory mismatches.

**What "Done" Looks Like:**

* **Enhanced Image Display:**  
  * All card images throughout the interface are increased by 300% in size.  
  * On the Card Details popup: The image is positioned on the left and spans the full height of the popup for optimal visibility.  
* **Location Field Standardization:** The "Location" field is converted from a text input to a mandatory dropdown menu to prevent spelling errors and ensure consistent searchability.  
* **Market Price Coverage:** The database/seeding script for market prices is updated to ensure 100% coverage across the card catalog.  
* **Inventory Input Validation:**  
  * The "Buy" workflow for Pokemon names is converted to a searchable dropdown (similar to the new location field) that pulls from the system's existing database.  
  * An "Override" option is provided for cards not found in the system; these instances are automatically flagged for future TCGdex entity matching.  
* **Condition Values:** The card condition system is updated (Frontend, Backend, and Database) to support "LP+" and "LP-" as selectable options.

