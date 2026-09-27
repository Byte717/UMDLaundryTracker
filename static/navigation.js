const menuToggle = document.querySelector("#menu-toggle");
const sidebarScrim = document.querySelector("#sidebar-scrim");

function setNavigationOpen(open) {
  document.body.classList.toggle("nav-open", open);
  if (window.matchMedia("(max-width: 900px)").matches) {
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Hide locations menu" : "Show locations menu");
  }
}

menuToggle.addEventListener("click", () => {
  if (window.matchMedia("(max-width: 900px)").matches) {
    setNavigationOpen(!document.body.classList.contains("nav-open"));
    return;
  }
  const hidden = !document.body.classList.contains("sidebar-hidden");
  document.body.classList.toggle("sidebar-hidden", hidden);
  menuToggle.setAttribute("aria-expanded", String(!hidden));
  menuToggle.setAttribute("aria-label", hidden ? "Show locations menu" : "Hide locations menu");
  localStorage.setItem("laundrytrack-sidebar-hidden", String(hidden));
});

sidebarScrim.addEventListener("click", () => setNavigationOpen(false));

if (!window.matchMedia("(max-width: 900px)").matches) {
  const sidebarHidden = localStorage.getItem("laundrytrack-sidebar-hidden") === "true";
  document.body.classList.toggle("sidebar-hidden", sidebarHidden);
  menuToggle.setAttribute("aria-expanded", String(!sidebarHidden));
  menuToggle.setAttribute("aria-label", sidebarHidden ? "Show locations menu" : "Hide locations menu");
} else {
  setNavigationOpen(false);
}

document.querySelectorAll(".tree-toggle").forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    const children = document.querySelector(`#${toggle.getAttribute("aria-controls")}`);
    toggle.setAttribute("aria-expanded", String(!expanded));
    children.classList.toggle("tree-collapsed", expanded);
  });
});
