/* Bahis Tahmin web arayüzü: küçük yardımcılar (satır içi betik yok; içerik güvenlik politikası 'self'). */
(function () {
  "use strict";
  var body = document.body;

  /* Menü (telefon) */
  var menuBtn = document.querySelector(".menu-btn");
  if (menuBtn) {
    menuBtn.addEventListener("click", function () {
      var open = body.classList.toggle("nav-open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.querySelectorAll(".sidebar a").forEach(function (a) {
      a.addEventListener("click", function () { body.classList.remove("nav-open"); });
    });
  }

  /* Arka plan işi: ilerleme çubuğu; iş bitince sayfa yenilenir (sonuç bildirimi bir kez gösterilir) */
  var job = document.getElementById("job");
  function poll(lastFinished) {
    fetch("/api/is", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s) { return; }
        if (job) {
          job.hidden = !s.busy;
          var fill = job.querySelector(".job-fill");
          var msg = job.querySelector(".job-msg");
          if (fill) { fill.style.width = s.pct + "%"; }
          if (msg) { msg.textContent = s.msg; }
        }
        if (!s.busy && s.finished !== lastFinished) {
          var url = new URL(window.location.href);
          url.searchParams.set("bitti", String(s.finished));
          window.location.replace(url.toString());
          return;
        }
        if (s.busy) { setTimeout(function () { poll(lastFinished); }, 1500); }
      })
      .catch(function () { setTimeout(function () { poll(lastFinished); }, 5000); });
  }
  if (body.dataset.busy === "1") { poll(parseInt(body.dataset.finished || "0", 10)); }

  /* Seçim değişince formu gönder */
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { if (el.form) { el.form.submit(); } });
  });
  document.querySelectorAll("[data-autosubmit-reset]").forEach(function (el) {
    el.addEventListener("change", function () {
      if (!el.form) { return; }
      el.dataset.autosubmitReset.split(",").forEach(function (n) {
        var f = el.form.elements[n];
        if (f) { f.value = ""; }
      });
      el.form.submit();
    });
  });

  /* Onay isteyen formlar */
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (!window.confirm(f.dataset.confirm)) { ev.preventDefault(); }
    });
  });

  /* Tablo sıralama: sayısal hücrelerde data-v, diğerlerinde metin */
  function cellValue(row, idx) {
    var c = row.children[idx];
    if (!c) { return ""; }
    var v = c.getAttribute("data-v");
    return v !== null ? v : c.textContent.trim();
  }
  document.querySelectorAll("table.data th[data-sort]").forEach(function (th) {
    th.addEventListener("click", function () {
      var table = th.closest("table");
      var tbody = table.tBodies[0];
      if (!tbody) { return; }
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var asc = th.getAttribute("aria-sort") !== "ascending";
      th.parentNode.querySelectorAll("th").forEach(function (o) { o.removeAttribute("aria-sort"); });
      th.setAttribute("aria-sort", asc ? "ascending" : "descending");
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var x = cellValue(a, idx), y = cellValue(b, idx);
        var nx = parseFloat(x), ny = parseFloat(y);
        var bothNum = x !== "" && y !== "" && !isNaN(nx) && !isNaN(ny) && isFinite(x) && isFinite(y);
        if (x === "" && y !== "") { return 1; }   /* boş değerler (gösterilmeyen olasılık) hep sonda */
        if (y === "" && x !== "") { return -1; }
        var r = bothNum ? nx - ny : x.localeCompare(y, "tr");
        return asc ? r : -r;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });

  /* Takım arama (sayfadaki tabloyu süzer; sunucuya da gönderilir) */
  document.querySelectorAll("[data-filter-table]").forEach(function (inp) {
    var table = document.getElementById(inp.dataset.filterTable);
    if (!table || !table.tBodies[0]) { return; }
    inp.addEventListener("input", function () {
      var q = inp.value.trim().toLocaleLowerCase("tr");
      Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
        r.hidden = q !== "" && r.textContent.toLocaleLowerCase("tr").indexOf(q) === -1;
      });
    });
  });

  /* Kupon: birden çok farklı maçın birlikte gerçekleşme olasılığı (bağımsızlık varsayımıyla) */
  var kupon = document.getElementById("kupon");
  var boxes = document.querySelectorAll("input.kupon");
  function updateKupon() {
    var chosen = Array.prototype.filter.call(boxes, function (b) { return b.checked; });
    if (!chosen.length) {
      kupon.textContent = "Birden çok maçın birlikte gerçekleşme olasılığını görmek için kutucukları işaretleyin.";
      return;
    }
    var seen = {}, dup = false, p = 1;
    chosen.forEach(function (b) {
      if (seen[b.dataset.match]) { dup = true; }
      seen[b.dataset.match] = true;
      p *= parseFloat(b.dataset.prob);
    });
    if (dup) {
      kupon.textContent = "Aynı maçtan birden fazla seçim işaretlendi. Aynı maçtaki seçimler birbirine bağımlıdır; " +
        "ortak olasılık bu ekranda hesaplanmaz. Her maçtan tek seçim bırakın.";
      return;
    }
    kupon.textContent = chosen.length + " farklı maç · birlikte gerçekleşme olasılığı yaklaşık %" +
      (100 * p).toFixed(1).replace(".", ",") + " (maçların birbirinden bağımsız olduğu varsayımıyla; kombine oran ve " +
      "beklenen kazanç, sağlayıcının gerçek kombine oranı olmadan hesaplanmaz. Her eklenen maç olasılığı düşürür.)";
  }
  if (kupon && boxes.length) {
    boxes.forEach(function (b) { b.addEventListener("change", updateKupon); });
  }

  /* Onay sayfası: beyan yalnızca indirme onayı işaretliyken verilebilir */
  document.querySelectorAll("input[data-consent]").forEach(function (c) {
    var d = document.querySelector('input[data-declaration="' + c.dataset.consent + '"]');
    if (!d) { return; }
    function sync() {
      if (!c.checked) { d.checked = false; }
      d.disabled = !c.checked;
    }
    c.addEventListener("change", sync);
    sync();
  });

  /* Veri sayfası: lig seçimi düğmeleri */
  document.querySelectorAll("button[data-leagues]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var spec = btn.dataset.leagues;
      var set = spec === "*" ? null : spec.split(",");
      document.querySelectorAll("input[data-code]").forEach(function (cb) {
        cb.checked = set === null ? true : set.indexOf(cb.dataset.code) !== -1;
      });
    });
  });
})();
