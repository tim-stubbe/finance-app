// ================= WUNSCHLISTE (Deal-Wecker) =================
let wishlistCache = [];

function wishlistItemIsOverdue(w) {
  if (!w.check_interval_days) return false;
  // Fallback auf created_at spiegelt main._scheduled_wishlist_reminder.
  const reference = new Date(w.last_checked_at || w.created_at);
  const days = (Date.now() - reference.getTime()) / (1000 * 60 * 60 * 24);
  return days >= w.check_interval_days;
}

async function loadWishlistTab() {
  wishlistCache = await api("/wishlist");
  const tbody = document.getElementById("wishlist-list");
  if (!wishlistCache.length) {
    tbody.innerHTML = emptyRow(6, "shopping-cart", "Noch nichts auf der Wunschliste – oben rechts einen Wunsch anlegen.");
    return;
  }
  tbody.innerHTML = wishlistCache.map(w => {
    const overdue = wishlistItemIsOverdue(w);
    const lastChecked = w.last_checked_at ? new Date(w.last_checked_at).toLocaleDateString("de-DE") : "noch nie";
    return `
      <tr>
        <td>${w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.name)}</a>` : esc(w.name)}</td>
        <td>${w.category ? esc(w.category) : "–"}</td>
        <td>${w.target_price != null ? eur(w.target_price) : "–"}</td>
        <td class="${overdue ? "row-amount-neg" : ""}">${overdue ? "⚠️ " : ""}${lastChecked}</td>
        <td>${w.auto_check_enabled ? "🤖 an" : "aus"}</td>
        <td>
          <button type="button" class="btn-ghost btn-sm" data-wishlist-checked="${w.id}">✓ Geprüft</button>
          <button type="button" class="link-btn" data-wishlist-edit="${w.id}">Bearbeiten</button>
        </td>
      </tr>`;
  }).join("");
}

document.getElementById("wishlist-list").addEventListener("click", async e => {
  const checkedId = e.target.closest("[data-wishlist-checked]")?.dataset.wishlistChecked;
  if (checkedId) {
    await api(`/wishlist/${checkedId}/checked`, { method: "POST" });
    toast("Als geprüft bestätigt.");
    loadWishlistTab();
    return;
  }
  const editId = e.target.closest("[data-wishlist-edit]")?.dataset.wishlistEdit;
  if (editId) {
    openWishlistModal(wishlistCache.find(w => w.id === parseInt(editId)));
  }
});

function openWishlistModal(item) {
  document.getElementById("wishlist-modal-title").textContent = item ? "Wunsch bearbeiten" : "Neuer Wunsch";
  document.getElementById("wishlist-id").value = item ? item.id : "";
  document.getElementById("wishlist-name").value = item ? item.name : "";
  document.getElementById("wishlist-category").value = item?.category || "";
  document.getElementById("wishlist-target-price").value = item?.target_price ?? "";
  document.getElementById("wishlist-url").value = item?.url || "";
  document.getElementById("wishlist-notes").value = item?.notes || "";
  document.getElementById("wishlist-interval").value = item?.check_interval_days || "";
  document.getElementById("wishlist-auto-check").checked = item?.auto_check_enabled || false;
  document.getElementById("wishlist-purchased").classList.toggle("hidden", !item);
  document.getElementById("wishlist-archive").classList.toggle("hidden", !item);
  document.getElementById("wishlist-modal").classList.remove("hidden");
}
document.getElementById("wishlist-new-btn").addEventListener("click", () => openWishlistModal(null));
document.getElementById("wishlist-modal-close").addEventListener("click", () => {
  document.getElementById("wishlist-modal").classList.add("hidden");
});

document.getElementById("wishlist-form").addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("wishlist-id").value;
  const priceVal = document.getElementById("wishlist-target-price").value;
  const payload = {
    name: document.getElementById("wishlist-name").value,
    category: document.getElementById("wishlist-category").value || null,
    target_price: priceVal !== "" ? parseFloat(priceVal) : null,
    url: document.getElementById("wishlist-url").value || null,
    notes: document.getElementById("wishlist-notes").value || null,
    check_interval_days: document.getElementById("wishlist-interval").value
      ? parseInt(document.getElementById("wishlist-interval").value) : null,
    auto_check_enabled: document.getElementById("wishlist-auto-check").checked,
  };
  if (id) {
    await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  } else {
    await api("/wishlist", { method: "POST", body: JSON.stringify(payload) });
  }
  document.getElementById("wishlist-modal").classList.add("hidden");
  loadWishlistTab();
});

document.getElementById("wishlist-purchased").addEventListener("click", async () => {
  const id = document.getElementById("wishlist-id").value;
  if (!id) return;
  await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify({ purchased: true, active: false }) });
  document.getElementById("wishlist-modal").classList.add("hidden");
  toast("Als gekauft markiert.");
  loadWishlistTab();
});

document.getElementById("wishlist-archive").addEventListener("click", async () => {
  const id = document.getElementById("wishlist-id").value;
  if (!id || !confirm("Wunsch entfernen?")) return;
  await api(`/wishlist/${id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
  document.getElementById("wishlist-modal").classList.add("hidden");
  loadWishlistTab();
});

