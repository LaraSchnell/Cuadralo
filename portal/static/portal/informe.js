/* Cuádralo · navegación del informe y gráficos.
   Los gráficos se dibujan en SVG a partir de las cifras que calcula el servidor (datos-graficos).
   Este archivo no calcula ninguna cifra del informe: solo la dibuja. */
(function () {
  'use strict';
  var C = window.CUADRALO || {};
  var G = JSON.parse(document.getElementById('datos-graficos').textContent);

  // ---------- formato español ----------
  function num(n, d) {
    d = d || 0;
    var s = Math.abs(n).toFixed(d).split('.');
    s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (n < 0 && Math.abs(n) >= Math.pow(10, -d) / 2 ? '−' : '') + s[0] + (s[1] ? ',' + s[1] : '');
  }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }

  // ---------- navegación entre páginas ----------
  function ir(p) {
    var destino = document.getElementById(p);
    if (!destino) {  // página que no existe en esta vista (p. ej. comparativa con un solo hotel): seguir el enlace
      var a = document.querySelector('.enlace[data-p="' + p + '"]');
      if (a) { window.location = a.href; }
      return;
    }
    document.querySelectorAll('.pagina').forEach(function (s) { s.classList.toggle('activa', s.id === p); });
    document.querySelectorAll('.enlace[data-p]').forEach(function (a) { a.classList.toggle('activo', a.dataset.p === p); });
    var campo = document.getElementById('f-p');
    if (campo) { campo.value = p; }
    if (history.replaceState) {
      var u = new URL(window.location.href);
      u.searchParams.set('p', p);
      history.replaceState(null, '', u.toString());
    }
    window.scrollTo(0, 0);
  }
  document.querySelectorAll('.enlace[data-p]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (document.getElementById(a.dataset.p)) { e.preventDefault(); ir(a.dataset.p); }
    });
  });
  document.querySelectorAll('[data-ir]').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); ir(a.dataset.ir); });
  });
  window.periodo = function (modo) {
    document.getElementById('f-periodo').value = modo;
    document.getElementById('filtros').submit();
  };
  ir(document.getElementById(C.pagina) ? C.pagina : 'resumen');

  // ---------- desviaciones: abrir los apuntes ----------
  document.querySelectorAll('.fila-desv').forEach(function (tr) {
    tr.addEventListener('click', function () {
      var f = document.getElementById(tr.dataset.fila);
      f.style.display = f.style.display === 'none' ? 'table-row' : 'none';
    });
  });

  // ---------- módulos opcionales: «Me interesa» ----------
  document.querySelectorAll('[data-modulo]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.classList.contains('hecho')) { return; }
      var datos = new FormData();
      datos.append('modulo', b.dataset.modulo);
      fetch(C.url_interes, {method: 'POST', body: datos, headers: {'X-CSRFToken': C.csrf}, credentials: 'same-origin'})
        .then(function (r) { if (r.ok) { b.classList.add('hecho'); b.textContent = 'Anotado · te avisaremos'; } });
    });
  });

  // ---------- gráfico de líneas (con huecos si falta un dato) ----------
  function lineas(id, etiquetas, series, opt) {
    var el = document.getElementById(id);
    if (!el) { return; }
    opt = opt || {};
    var W = 640, H = 230, L = 44, R = 12, T = 12, B = 26;
    var todos = [];
    series.forEach(function (s) { s.v.forEach(function (v) { if (v !== null) { todos.push(v); } }); });
    if (!todos.length) { el.innerHTML = '<p class="vacio">Sin datos para este gráfico.</p>'; return; }
    var mn = opt.min !== undefined ? opt.min : Math.min.apply(null, todos), mx = Math.max.apply(null, todos);
    if (mx === mn) { mx = mn + 1; }
    var pad = (mx - mn) * 0.08; mn = opt.min !== undefined ? mn : mn - pad; mx += pad;
    var x = function (i) { return L + i * (W - L - R) / (etiquetas.length - 1); };
    var y = function (v) { return T + (1 - (v - mn) / (mx - mn)) * (H - T - B); };
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">';
    for (var g = 0; g <= 4; g++) {
      var gv = mn + (mx - mn) * g / 4;
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(gv) + '" y2="' + y(gv) + '" stroke="#E9ECEF"/>' +
           '<text x="' + (L - 6) + '" y="' + (y(gv) + 4) + '" font-size="10" fill="#94A3B8" text-anchor="end">' + num(gv, opt.dec || 0) + '</text>';
    }
    etiquetas.forEach(function (l, i) {
      s += '<text x="' + x(i) + '" y="' + (H - 8) + '" font-size="10" fill="#94A3B8" text-anchor="middle">' + esc(l) + '</text>';
    });
    series.forEach(function (se) {
      var tramo = [];
      var dibujar = function () {
        if (tramo.length > 1) {
          s += '<polyline points="' + tramo.join(' ') + '" fill="none" stroke="' + se.c + '" stroke-width="' + (se.w || 2) + '"' +
               (se.discontinua ? ' stroke-dasharray="4 4"' : '') + ' stroke-linejoin="round"/>';
        }
        tramo = [];
      };
      se.v.forEach(function (v, i) { if (v === null) { dibujar(); } else { tramo.push(x(i) + ',' + y(v)); } });
      dibujar();
      se.v.forEach(function (v, i) {
        if (v !== null) {
          s += '<circle cx="' + x(i) + '" cy="' + y(v) + '" r="' + (i === se.v.length - 1 ? 3.5 : 2) + '" fill="' + se.c + '">' +
               '<title>' + esc(se.n) + ' · ' + esc(etiquetas[i]) + ': ' + num(v, opt.dec || 0) + (opt.unidad || '') + '</title></circle>';
        }
      });
    });
    el.innerHTML = s + '</svg>';
  }
  var miles = function (a) { return a.map(function (v) { return v === null ? null : v / 1000; }); };
  lineas('g-ingresos', G.etiquetas, [
    {n: 'Año anterior', c: '#CBD5E1', v: miles(G.ingresos_aa), discontinua: true},
    {n: 'Presupuesto', c: '#94A3B8', v: miles(G.ingresos_ppto), discontinua: true},
    {n: 'Ingresos', c: '#0F172A', v: miles(G.ingresos), w: 2.5},
    {n: 'GOP', c: '#10B981', v: miles(G.gop), w: 2.5}
  ], {min: 0, unidad: ' k€'});
  lineas('g-ocupacion', G.etiquetas, [
    {n: 'Año anterior', c: '#CBD5E1', v: G.ocupacion_aa, discontinua: true},
    {n: 'Ocupación', c: '#0F172A', v: G.ocupacion, w: 2.5}
  ], {unidad: ' %'});
  lineas('g-adr', G.etiquetas, [
    {n: 'Año anterior', c: '#CBD5E1', v: G.adr_aa, discontinua: true},
    {n: 'ADR', c: '#0F172A', v: G.adr, w: 2.5}
  ], {unidad: ' €'});

  // ---------- cascada de ingresos a GOP2 ----------
  (function () {
    var el = document.getElementById('g-cascada');
    if (!el || !G.cascada.length) { return; }
    var pasos = G.cascada, W = 760, H = 240, L = 8, B = 34, T = 20, bw = (W - L * 2) / pasos.length;
    var mx = pasos[0][1], y = function (v) { return T + (1 - v / mx) * (H - T - B); };
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">', acumulado = 0;
    pasos.forEach(function (p, i) {
      var xx = L + i * bw + bw * 0.15, w = bw * 0.7, arriba, abajo, color;
      if (p[2]) { arriba = p[1]; abajo = 0; acumulado = p[1]; color = '#0F172A'; }
      else { arriba = acumulado; abajo = acumulado + p[1]; acumulado = abajo; color = '#EF4444'; }
      s += '<rect x="' + xx + '" y="' + y(arriba) + '" width="' + w + '" height="' + Math.max(1, y(abajo) - y(arriba)) +
           '" rx="3" fill="' + color + '"><title>' + esc(p[0]) + ': ' + num(p[1]) + ' €</title></rect>';
      s += '<text x="' + (xx + w / 2) + '" y="' + (y(arriba) - 6) + '" font-size="11" text-anchor="middle" fill="#0F172A" font-weight="600">' +
           num(p[1] / 1000, 1) + ' k</text>';
      s += '<text x="' + (xx + w / 2) + '" y="' + (H - 14) + '" font-size="11" text-anchor="middle" fill="#64748B">' + esc(p[0]) + '</text>';
      if (i < pasos.length - 1) {
        s += '<line x1="' + (xx + w) + '" x2="' + (xx + bw) + '" y1="' + y(acumulado) + '" y2="' + y(acumulado) + '" stroke="#CBD5E1" stroke-dasharray="3 3"/>';
      }
    });
    el.innerHTML = s + '</svg>';
  })();

  // ---------- coste por room night: barras con la marca del presupuesto ----------
  (function () {
    var el = document.getElementById('g-coste-rn');
    if (!el) { return; }
    if (!G.coste_rn.length) { el.innerHTML = '<p class="vacio">Sin datos.</p>'; return; }
    var mx = 0;
    G.coste_rn.forEach(function (r) { mx = Math.max(mx, r.real, r.ppto || 0); });
    el.innerHTML = G.coste_rn.map(function (r) {
      var color = r.ppto === null ? '#0F172A' : (r.real > r.ppto ? '#EF4444' : '#10B981');
      return '<div class="barra-h"><div>' + esc(r.linea) + '</div><div class="pista">' +
        '<div class="real" style="width:' + (r.real / mx * 100) + '%;background:' + color + '"></div>' +
        (r.ppto !== null ? '<div class="ppto" style="left:' + (r.ppto / mx * 100) + '%" title="Presupuesto ' + num(r.ppto, 2) + ' €"></div>' : '') +
        '</div><div class="v">' + num(r.real, 2) + ' €</div></div>';
    }).join('');
  })();
})();
