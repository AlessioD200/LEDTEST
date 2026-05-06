let sidebar = document.getElementById("sidebar");
let topbar = document.getElementById("topbar");
let lastScroll = 0;

/* ===== PAGE SWITCH ===== */
function switchPage(id) {
	document.querySelectorAll(".page").forEach(p => {
		p.classList.remove("active");
	});

	document.getElementById(id).classList.add("active");

	document.querySelectorAll(".nav-btn").forEach(b => {
		b.classList.remove("active");
	});

	event.target.classList.add("active");
}

/* ===== SWIPE OPEN MENU ===== */
let startX = 0;

document.addEventListener("touchstart", e => {
	startX = e.touches[0].clientX;
});

document.addEventListener("touchend", e => {
	let endX = e.changedTouches[0].clientX;

	// swipe right
	if (endX - startX > 80) {
		sidebar.classList.add("open");
	}

	// swipe left
	if (startX - endX > 80) {
		sidebar.classList.remove("open");
	}
});

/* ===== AUTO HIDE TOPBAR ===== */
window.addEventListener("scroll", () => {
	let current = window.scrollY;

	if (current > lastScroll && current > 50) {
		topbar.classList.add("hide");
	} else {
		topbar.classList.remove("hide");
	}

	lastScroll = current;
});

/* close menu on tap outside */
document.addEventListener("click", (e) => {
	if (!sidebar.contains(e.target)) {
		sidebar.classList.remove("open");
	}
});