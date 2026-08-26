// ================= PROFILE =================
async function loadProfile() {
  const profile = await api("/auth/profile");
  document.getElementById("profile-name").value = profile.display_name;
  await loadBenchmark();
}

document.getElementById("profile-form").addEventListener("submit", async e => {
  e.preventDefault();
  const display_name = document.getElementById("profile-name").value;
  await api("/auth/profile", { method: "PUT", body: JSON.stringify({ display_name }) });
  toast("Profil gespeichert.");
});

