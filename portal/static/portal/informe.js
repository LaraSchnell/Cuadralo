/* Cuádralo · navegación del informe, filtros, gráficos y tablas de detalle.
   Los gráficos se dibujan con Chart.js a partir de lo que calcula el servidor (datos-graficos): cada punto
   trae su valor, el texto que va encima y el de la ayuda (tooltip) ya escritos. Este archivo no calcula
   ninguna cifra del informe: solo la dibuja y, al hacer clic, pide al servidor la tabla de detalle. */
(function () {
  'use strict';
  var C = window.CUADRALO || {};
  var G = JSON.parse(document.getElementById('datos-graficos').textContent);
  var graficos = {};          // gráficos ya dibujados, por id de lienzo

  // ---------- formato español (solo para los ejes) ----------
  function num(n, d) {
    d = d || 0;
    var s = Math.abs(n).toFixed(d).split('.');
    s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (n < 0 && Math.abs(n) >= Math.pow(10, -d) / 2 ? '−' : '') + s[0] + (s[1] ? ',' + s[1] : '');
  }
  function eje(formato) {
    return function (v) {
      if (formato === 'pct') { return num(v) + ' %'; }
      if (formato === 'eur' || formato === 'eur2') {
        var a = Math.abs(v);
        if (a >= 1e6) { return num(v / 1e6, 1) + ' M€'; }
        if (a >= 1e3) { return num(v / 1e3) + ' k€'; }
        return num(v) + ' €';
      }
      return num(v);
    };
  }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }

  // ---------- colores ----------
  var COLOR = {principal: '#2563EB', comparacion: '#CBD5E1', gasto: '#F59E0B', resultado: '#10B981',
               divergente: '#64748B', bien: '#10B981', mal: '#EF4444'};
  var PALETA = ['#2563EB', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#94A3B8'];
  function claro(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // ---------- navegación entre páginas ----------
  function ir(p) {
    var destino = document.getElementById(p);
    if (!destino) {
      var a = document.querySelector('.enlace[data-p="' + p + '"]');
      if (a) { window.location = a.href + (C.query ? '&' + C.query : ''); }
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
    dibujarPagina(destino);
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

  // ---------- filtros desplegables ----------
  var desplegables = document.querySelectorAll('[data-desplegable]');
  desplegables.forEach(function (d) {
    d.querySelector('.disparador').addEventListener('click', function (e) {
      e.stopPropagation();
      var abrir = !d.classList.contains('abierto');
      desplegables.forEach(function (x) { x.classList.remove('abierto'); });
      d.classList.toggle('abierto', abrir);
      var b = d.querySelector('[data-buscar]');
      if (abrir && b) { b.focus(); }
    });
    d.querySelector('.panel').addEventListener('click', function (e) { e.stopPropagation(); });
  });
  document.addEventListener('click', function () { desplegables.forEach(function (x) { x.classList.remove('abierto'); }); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { desplegables.forEach(function (x) { x.classList.remove('abierto'); }); }
  });
  document.querySelectorAll('[data-buscar]').forEach(function (b) {
    b.addEventListener('input', function () {
      var t = b.value.toLowerCase();
      b.closest('.panel').querySelectorAll('.opcion').forEach(function (o) {
        o.style.display = o.textContent.toLowerCase().indexOf(t) >= 0 ? '' : 'none';
      });
    });
  });
  // año > mes: marcar el año marca todos sus meses
  var casillasMes = Array.prototype.slice.call(document.querySelectorAll('input[name="meses"]'));
  function repasarAnios() {
    document.querySelectorAll('input[data-anio]').forEach(function (a) {
      var suyos = casillasMes.filter(function (m) { return m.dataset.de === a.dataset.anio; });
      var marcados = suyos.filter(function (m) { return m.checked; }).length;
      a.checked = marcados === suyos.length && marcados > 0;
      a.indeterminate = marcados > 0 && marcados < suyos.length;
    });
  }
  document.querySelectorAll('input[data-anio]').forEach(function (a) {
    a.addEventListener('change', function () {
      casillasMes.forEach(function (m) { if (m.dataset.de === a.dataset.anio) { m.checked = a.checked; } });
      repasarAnios();
    });
  });
  casillasMes.forEach(function (m) { m.addEventListener('change', repasarAnios); });
  repasarAnios();
  document.querySelectorAll('[data-rapido]').forEach(function (b) {
    b.addEventListener('click', function () {
      var orden = casillasMes.slice().sort(function (x, y) { return x.value < y.value ? 1 : -1; });   // más reciente primero
      var r = b.dataset.rapido, marcar = [];
      if (r === 'ultimo') { marcar = orden.slice(0, 1); }
      if (r === 'tres') { marcar = orden.slice(0, 3); }
      if (r === 'anio' && orden.length) {
        var anio = orden[0].value.slice(0, 4);
        marcar = orden.filter(function (m) { return m.value.slice(0, 4) === anio; });
      }
      casillasMes.forEach(function (m) { m.checked = marcar.indexOf(m) >= 0; });
      repasarAnios();
      if (r !== 'nada') { document.getElementById('filtros').submit(); }
    });
  });
  var form = document.getElementById('filtros');
  if (form) {
    form.addEventListener('submit', function (e) {   // sin ningún mes marcado se vuelve al último mes
      if (casillasMes.length && !casillasMes.some(function (m) { return m.checked; })) {
        casillasMes.sort(function (x, y) { return x.value < y.value ? 1 : -1; })[0].checked = true;
      }
    });
  }

  // ---------- gráficos ----------
  if (window.Chart) {
    Chart.register(window.ChartDataLabels);
    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#64748B';
  }

  function colorSerie(s, i, n, tipo) {
    if (tipo === 'donut') { return PALETA.slice(0, n); }
    if (s.colores) { return s.colores.map(function (c) { return COLOR[c] || COLOR.principal; }); }
    return COLOR[s.color] || PALETA[i % PALETA.length];
  }

  function crear(lienzo) {
    var clave = lienzo.dataset.grafico, g = G[clave];
    if (!g || !window.Chart) { return; }
    var tipo = g.tipo, horizontal = tipo === 'barras_h', n = g.etiquetas.length;
    if (horizontal) {   // altura según el número de barras
      lienzo.parentElement.style.height = Math.max(160, (g.series.length > 1 ? 32 : 27) * n + 50) + 'px';
    }
    var datasets = g.series.map(function (s, i) {
      var color = colorSerie(s, i, n, tipo);
      var d = {label: s.nombre, data: s.valores, backgroundColor: color, borderColor: color, borderRadius: tipo === 'donut' ? 0 : 5,
               maxBarThickness: horizontal ? 22 : 46, _serie: s};
      if (tipo === 'lineas' || s.tipo === 'line') {
        d.type = 'line'; d.backgroundColor = claro(COLOR[s.color] || PALETA[i], 0.12); d.fill = false; d.tension = 0.3;
        d.pointRadius = 4; d.pointHoverRadius = 6; d.borderWidth = 2.5;
      }
      if (tipo === 'cascada') {
        var acumulado = 0;
        d.data = s.valores.map(function (v, k) {
          if (g.totales[k]) { acumulado = v; return [0, v]; }
          var desde = acumulado; acumulado += v; return [desde, acumulado];
        });
        d.backgroundColor = s.valores.map(function (v, k) { return g.totales[k] ? COLOR.principal : (v < 0 ? '#FCA5A5' : COLOR.resultado); });
      }
      return d;
    });
    var opciones = {
      responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x',
      layout: {padding: {top: horizontal ? 0 : 22, right: horizontal ? 70 : 8}},
      interaction: {mode: tipo === 'lineas' ? 'index' : 'nearest', intersect: tipo !== 'lineas'},
      plugins: {
        legend: {display: g.series.length > 1 || tipo === 'donut', position: tipo === 'donut' ? 'right' : 'top', align: 'end',
                 labels: {boxWidth: 12, boxHeight: 12, usePointStyle: true}},
        tooltip: {
          backgroundColor: '#0F172A', padding: 10, titleFont: {weight: '600'}, bodySpacing: 3,
          callbacks: {
            label: function (ctx) {
              var s = ctx.dataset._serie, t = s.ayudas[ctx.dataIndex] || '';
              var partes = t.split(' · ');
              partes[0] = (g.series.length > 1 ? s.nombre + ': ' : '') + partes[0];
              return partes;
            }
          }
        },
        datalabels: {
          display: function (ctx) {
            var s = ctx.dataset._serie;
            return s.etiquetas_visibles !== false && !!s.textos[ctx.dataIndex] && (tipo !== 'donut' || ctx.dataset.data[ctx.dataIndex] > 0);
          },
          formatter: function (v, ctx) { return ctx.dataset._serie.textos[ctx.dataIndex]; },
          anchor: tipo === 'donut' ? 'center' : 'end',
          align: function (ctx) {
            if (tipo === 'donut') { return 'center'; }
            if (horizontal) { return 'end'; }
            return tipo === 'lineas' && ctx.datasetIndex > 0 ? 'bottom' : 'top';   // en líneas, la 2ª serie lleva el texto debajo
          },
          offset: 2, clamp: true,
          color: tipo === 'donut' ? '#fff' : '#334155', font: {size: 11, weight: '600'}
        }
      },
      onHover: function (e, el) { e.native.target.style.cursor = el.length && g.clic[el[0].index] ? 'pointer' : 'default'; },
      onClick: function (e, el) {
        if (!el.length) { return; }
        var k = el[0].index, filtro = g.clic[k];
        if (!filtro) { return; }
        resaltar(lienzo, k);
        abrirDetalle(filtro, lienzo.dataset.pagina);
      }
    };
    if (tipo !== 'donut') {
      var ejeValor = {beginAtZero: tipo !== 'lineas', grace: tipo === 'lineas' ? '15%' : 0, grid: {color: '#F1F5F9'}, border: {display: false}, ticks: {callback: eje(g.formato), maxTicksLimit: 6}};
      var ejeCategoria = {grid: {display: false}, border: {display: false}, ticks: {autoSkip: false}};
      opciones.scales = horizontal ? {x: ejeValor, y: ejeCategoria} : {x: ejeCategoria, y: ejeValor};
      if (tipo === 'cascada') { opciones.plugins.legend.display = false; }
    } else {
      opciones.cutout = '58%';
    }
    graficos[clave + '-' + lienzo.dataset.pagina] = new Chart(lienzo, {type: tipo === 'donut' ? 'doughnut' : (tipo === 'lineas' ? 'line' : 'bar'),
                                                                       data: {labels: g.etiquetas, datasets: datasets}, options: opciones});
    lienzo._clave = clave + '-' + lienzo.dataset.pagina;
  }

  function resaltar(lienzo, k) {   // el elemento elegido se queda con su color y el resto se aclara
    var ch = graficos[lienzo._clave];
    if (!ch) { return; }
    ch.data.datasets.forEach(function (d) {
      if (d._original === undefined) { d._original = d.backgroundColor; }
      var base = d._original;
      d.backgroundColor = d.data.map(function (_, i) {
        var c = Array.isArray(base) ? base[i] : base;
        if (k === null || i === k || typeof c !== 'string' || c.charAt(0) !== '#') { return c; }
        return claro(c, 0.3);
      });
    });
    ch.update();
  }

  function dibujarPagina(seccion) {
    seccion.querySelectorAll('canvas[data-grafico]').forEach(function (l) {
      if (!l._clave) { crear(l); }
    });
  }

  // ---------- tabla de detalle: de dónde sale cada cifra ----------
  var NOMBRES = {mes: 'mes_sel', hotel: 'hotel_sel'};
  function abrirDetalle(filtro, pagina) {
    if (filtro.tipo === 'hotel') {   // clic en un hotel: ver la página con solo ese hotel
      window.location = '?' + C.query.replace(/(^|&)hotel=[^&]*/g, '') + '&hotel=' + encodeURIComponent(filtro.hotel) + '&p=' + pagina;
      return;
    }
    var caja = document.getElementById('detalle-' + pagina);
    if (!caja) { return; }
    var params = new URLSearchParams(C.query);
    Object.keys(filtro).forEach(function (k) { params.set(NOMBRES[k] || k, filtro[k]); });
    caja.querySelector('.d-titulo').textContent = 'Cargando…';
    caja.classList.add('con-datos');
    fetch(C.url_detalle + '?' + params.toString(), {credentials: 'same-origin'})
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
      .then(function (d) { pintarDetalle(caja, d); caja.scrollIntoView({behavior: 'smooth', block: 'start'}); })
      .catch(function () { caja.querySelector('.d-titulo').textContent = 'No se ha podido cargar el detalle'; });
  }

  function pintarDetalle(caja, d) {
    caja.querySelector('.d-titulo').textContent = d.titulo;
    caja.querySelector('.d-ayuda').hidden = true;
    var ul = caja.querySelector('.d-explicacion');
    ul.innerHTML = (d.explicacion || []).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('');
    ul.hidden = !(d.explicacion || []).length;
    var tabla = caja.querySelector('.d-tabla'), numericas = d.numericas || [];
    tabla.querySelector('thead').innerHTML = '<tr>' + d.columnas.map(function (c, i) {
      return '<th' + (numericas.indexOf(i) >= 0 ? ' class="d"' : '') + '>' + esc(c) + '</th>';
    }).join('') + '</tr>';
    tabla.querySelector('tbody').innerHTML = d.filas.map(function (f) {
      return '<tr>' + f.map(function (v, i) { return '<td' + (numericas.indexOf(i) >= 0 ? ' class="d"' : '') + '>' + esc(v) + '</td>'; }).join('') + '</tr>';
    }).join('');
    tabla.hidden = !d.columnas.length;
    var pie = caja.querySelector('.d-pie');
    pie.hidden = false;
    pie.textContent = d.total_filas > d.filas.length
      ? 'Se muestran ' + num(d.filas.length) + ' de ' + num(d.total_filas) + ' filas' + (d.orden ? ' (' + d.orden + ')' : '') + '.'
      : num(d.total_filas) + ' filas.';
    var exp = caja.querySelector('.d-exportar');
    exp.hidden = !d.exportar;
    if (d.exportar) { exp.href = d.exportar; }
    caja.querySelector('.d-quitar').hidden = false;
  }

  document.querySelectorAll('.detalle-clic .d-quitar').forEach(function (b) {
    b.addEventListener('click', function () {
      var caja = b.closest('.detalle-clic');
      caja.classList.remove('con-datos');
      caja.querySelector('.d-titulo').textContent = '¿De dónde sale cada cifra?';
      ['.d-explicacion', '.d-tabla', '.d-pie', '.d-exportar'].forEach(function (s) { caja.querySelector(s).hidden = true; });
      caja.querySelector('.d-ayuda').hidden = false;
      b.hidden = true;
      var seccion = caja.closest('.pagina');
      seccion.querySelectorAll('canvas[data-grafico]').forEach(function (l) { if (l._clave) { resaltar(l, null); } });
      seccion.querySelectorAll('.fila-clic.elegida').forEach(function (f) { f.classList.remove('elegida'); });
    });
  });
  document.querySelectorAll('.fila-clic[data-clic]').forEach(function (tr) {
    tr.addEventListener('click', function () {
      tr.closest('table').querySelectorAll('.elegida').forEach(function (f) { f.classList.remove('elegida'); });
      tr.classList.add('elegida');
      abrirDetalle(JSON.parse(tr.dataset.clic), tr.dataset.pagina);
    });
  });
  document.querySelectorAll('[data-ver-todo]').forEach(function (b) {
    b.addEventListener('click', function () { abrirDetalle(JSON.parse(b.dataset.verTodo), b.dataset.pagina); });
  });
  document.querySelectorAll('[data-abrir-detalle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = b.closest('.tarjeta').querySelector('table');
      t.classList.toggle('abierta');
      b.textContent = t.classList.contains('abierta') ? 'Ver solo los totales' : 'Ver todas las líneas';
    });
  });
  document.querySelectorAll('[data-mostrar-todo]').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = document.getElementById(b.dataset.mostrarTodo);
      if (!b.dataset.texto) { b.dataset.texto = b.textContent; }
      t.classList.toggle('todo');
      b.textContent = t.classList.contains('todo') ? 'Ver solo lo que hay que revisar' : b.dataset.texto;
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

  ir(document.getElementById(C.pagina) ? C.pagina : 'resumen');
})();
