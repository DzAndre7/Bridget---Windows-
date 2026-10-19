(function(){
  var canvas = document.getElementById('bcanvas');
  var ctx = canvas.getContext('2d');
  var W, H, cx, cy;

  function resize(){
    var rect = canvas.getBoundingClientRect();
    W = canvas.width = rect.width;
    H = canvas.height = rect.height;
    cx = W/2; cy = H/2;
  }
  window.addEventListener('resize', resize);

  var t = 0, modo = 'reposo';
  var sacudida = 0; // se dispara al empujar, y decae: hace "reaccionar" a la presencia

  var cfg = {
    col: '40,140,150',
    cant: 140, disp: 100, vel: 100, sz: 100,
    react: 100, core: 100, flat: 78, opac: 65
  };

  // --- Cargar configuración guardada (si existe) ---
  function aplicarConfigGuardada(){
    if(window.pywebview && window.pywebview.api){
      window.pywebview.api.cargar_config().then(function(txt){
        if(txt){
          try {
            var guardada = JSON.parse(txt);
            for(var k in guardada){ if(k in cfg) cfg[k] = guardada[k]; }
            sincronizarControles();
          } catch(e){}
        }
      });
    }
  }

  // --- Guardar configuración en disco ---
  var guardarTimer = null;
  function guardarConfig(){
    if(!(window.pywebview && window.pywebview.api)) return;
    // esperamos un poquito para no guardar en cada micro-movimiento del slider
    clearTimeout(guardarTimer);
    guardarTimer = setTimeout(function(){
      window.pywebview.api.guardar_config(JSON.stringify(cfg));
    }, 400);
  }

  var P = [];
  function rebuild(n){
    P = [];
    for(var i=0;i<n;i++){
      P.push({
        a: Math.random()*Math.PI*2,
        r: 30 + Math.random()*95,
        s: 0.25 + Math.random()*0.9,
        sz: 0.6 + Math.random()*1.8,
        tw: Math.random()*Math.PI*2
      });
    }
  }
  rebuild(cfg.cant);

  function voz(){
    var base = (modo==='reposo')
      ? (0.12 + 0.06*Math.sin(t*0.04))
      : (0.45 + 0.55*Math.abs(Math.sin(t*0.07))*(0.55+0.45*Math.sin(t*0.21)));
    return base * (cfg.react/100) + sacudida;
  }

  function loop(){
    t += cfg.vel/100;
    if(sacudida > 0) sacudida *= 0.92; // la reacción al empujón se calma de a poco
    ctx.clearRect(0,0,W,H);
    var v = voz();
    var col = cfg.col;
    var flat = cfg.flat/100;

    if(cfg.core > 0){
      var coreR = (5 + v*5) * (cfg.core/100);
      var g = ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(1,coreR*4));
      g.addColorStop(0,'rgba('+col+','+(0.5+v*0.4)+')');
      g.addColorStop(1,'rgba('+col+',0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx,cy,Math.max(1,coreR*4),0,Math.PI*2); ctx.fill();
      ctx.beginPath(); ctx.arc(cx,cy,coreR,0,Math.PI*2);
      ctx.fillStyle = 'rgba(235,250,252,'+(0.7+v*0.3)+')'; ctx.fill();
    }

    for(var i=0;i<P.length;i++){
      var p = P[i];
      p.a += 0.0016*p.s*(0.5+v);
      p.tw += 0.05;
      var rr = (p.r*(cfg.disp/100)) + v*55*p.s*(cfg.disp/100);
      var x = cx + Math.cos(p.a)*rr;
      var y = cy + Math.sin(p.a)*rr*flat;
      var alpha = (0.15 + v*0.55)*(0.6+0.4*Math.sin(p.tw));
      var size = p.sz*(0.5+v*0.9)*(cfg.sz/100);
      ctx.beginPath();
      ctx.arc(x,y,Math.max(0.2,size),0,Math.PI*2);
      ctx.fillStyle = 'rgba('+col+','+alpha+')';
      ctx.fill();
    }
    requestAnimationFrame(loop);
  }
  resize();
  loop();

  // --- Panel: abrir / cerrar con empujón ---
  var btn = document.getElementById('btn-panel');
  var panel = document.getElementById('panel');
  var escenario = document.getElementById('escenario');

  btn.addEventListener('click', function(){
    var abierto = panel.classList.toggle('abierto');
    escenario.classList.toggle('empujado', abierto);
    sacudida = 0.35; // la presencia "siente" el empujón
    // recalculamos el centro después de que termine la transición
    setTimeout(resize, 360);
  });

  // --- Controles del editor ---
  function bind(id, key, out){
    var el = document.getElementById(id);
    el.addEventListener('input', function(){
      cfg[key] = +el.value;
      document.getElementById(out).textContent = el.value;
      if(key === 'cant') rebuild(cfg.cant);
      guardarConfig();
    });
  }
  bind('s-cant','cant','v-cant');
  bind('s-disp','disp','v-disp');
  bind('s-vel','vel','v-vel');
  bind('s-sz','sz','v-sz');
  bind('s-react','react','v-react');
  bind('s-core','core','v-core');
  bind('s-flat','flat','v-flat');

  // Control de opacidad del fondo
  var escenarioEl = document.getElementById('escenario');
  function aplicarFondo(){
    escenarioEl.style.background = 'rgba(10, 14, 20, ' + (cfg.opac/100) + ')';
  }

  aplicarFondo(); // aplica el valor inicial

  document.getElementById('s-opac').addEventListener('input', function(){
    cfg.opac = +this.value;
    document.getElementById('v-opac').textContent = this.value;
    aplicarFondo();
    guardarConfig();
  });

  // Selector RGB
  var sR = document.getElementById('s-r');
  var sG = document.getElementById('s-g');
  var sB = document.getElementById('s-b');
  var preview = document.getElementById('preview-color');
  var vColor = document.getElementById('v-color');

  function actualizarColor(){
    var r = +sR.value, g = +sG.value, b = +sB.value;
    cfg.col = r + ',' + g + ',' + b;
    preview.style.background = 'rgb(' + cfg.col + ')';
    vColor.textContent = r + ', ' + g + ', ' + b;
    document.getElementById('blabel').style.color = 'rgb(' + cfg.col + ')';
  }

  sR.addEventListener('input', function(){ actualizarColor(); guardarConfig(); });
  sG.addEventListener('input', function(){ actualizarColor(); guardarConfig(); });
  sB.addEventListener('input', function(){ actualizarColor(); guardarConfig(); });
  actualizarColor(); // aplica el valor inicial

  // Pone todos los controles en sus valores actuales de cfg
  function sincronizarControles(){
    document.getElementById('s-cant').value = cfg.cant;  document.getElementById('v-cant').textContent = cfg.cant;
    document.getElementById('s-disp').value = cfg.disp;  document.getElementById('v-disp').textContent = cfg.disp;
    document.getElementById('s-vel').value  = cfg.vel;   document.getElementById('v-vel').textContent  = cfg.vel;
    document.getElementById('s-sz').value   = cfg.sz;    document.getElementById('v-sz').textContent   = cfg.sz;
    document.getElementById('s-react').value= cfg.react; document.getElementById('v-react').textContent= cfg.react;
    document.getElementById('s-core').value = cfg.core;  document.getElementById('v-core').textContent = cfg.core;
    document.getElementById('s-flat').value = cfg.flat;  document.getElementById('v-flat').textContent = cfg.flat;
    document.getElementById('s-opac').value = cfg.opac;  document.getElementById('v-opac').textContent = cfg.opac;
    var rgb = cfg.col.split(',');
    document.getElementById('s-r').value = rgb[0];
    document.getElementById('s-g').value = rgb[1];
    document.getElementById('s-b').value = rgb[2];
    rebuild(cfg.cant);
    actualizarColor();
    aplicarFondo();
  }

  window.setEstado = function(m){ modo = m; };
  window.addEventListener('pywebviewready', aplicarConfigGuardada);

  // --- Chat ---
  var inputChat = document.getElementById('input-chat');
  var btnEnviar = document.getElementById('btn-enviar');
  var mensajesEl = document.getElementById('mensajes');

  function agregarMensaje(texto, quien){
    var div = document.createElement('div');
    div.className = 'msg ' + (quien === 'user' ? 'msg-user' : 'msg-bridget');

    var textoDiv = document.createElement('div');
    textoDiv.textContent = texto;
    div.appendChild(textoDiv);

    // Los mensajes de Bridget tienen botón de reproducción
    if(quien === 'bridget'){
      var btnVoz = document.createElement('button');
      btnVoz.className = 'btn-voz';
      btnVoz.textContent = '▶';
      btnVoz.dataset.estado = 'none';
      btnVoz.addEventListener('click', function(){ reproducirVoz(texto, btnVoz); });
      div.appendChild(btnVoz);
    }

    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
  }

  function enviarMensaje(){
    var texto = inputChat.value.trim();
    if(!texto) return;
    agregarMensaje(texto, 'user');
    inputChat.value = '';

    // Bridget "piensa": cambiamos el estado de la presencia
    modo = 'hablando';

    // Mostramos un indicador mientras el cerebro procesa
    var pensando = document.createElement('div');
    pensando.className = 'msg msg-bridget';
    pensando.textContent = '...';
    pensando.id = 'pensando-temp';
    mensajesEl.appendChild(pensando);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;

    if(window.pywebview && window.pywebview.api){
      window.pywebview.api.enviar_mensaje(texto).then(function(respuesta){
        // sacamos el indicador "..."
        var temp = document.getElementById('pensando-temp');
        if(temp) temp.remove();
        agregarMensaje(respuesta, 'bridget');
        modo = 'reposo';
      });
    }
  }

  btnEnviar.addEventListener('click', enviarMensaje);
  inputChat.addEventListener('keydown', function(e){
    if(e.key === 'Enter') enviarMensaje();
  });

  // --- Persistencia: al abrir, mostramos la conversación de la sesión anterior ---
  function agregarSeparador(texto){
    var sep = document.createElement('div');
    sep.className = 'sep-sesion';
    sep.textContent = texto;
    mensajesEl.appendChild(sep);
  }

  function cargarHistorialAnterior(){
    if(!(window.pywebview && window.pywebview.api && window.pywebview.api.obtener_historial_anterior)) return;
    window.pywebview.api.obtener_historial_anterior().then(function(mensajes){
      if(!mensajes || !mensajes.length) return;
      agregarSeparador('— sesión anterior —');
      mensajes.forEach(function(m){
        agregarMensaje(m.texto, m.quien);
      });
      agregarSeparador('— hoy —');
    });
  }
  window.addEventListener('pywebviewready', cargarHistorialAnterior);
  // por si pywebview ya estaba listo cuando corrió este script
  if(window.pywebview && window.pywebview.api) cargarHistorialAnterior();

  // --- Reproducción de voz por mensaje (calcado de la web) ---
  function reproducirVoz(texto, btn){
    var estado = btn.dataset.estado;

    // Si todavía no se generó el audio, lo pedimos a Python
    if(estado === 'none'){
      btn.textContent = '…';
      btn.disabled = true;
      btn.dataset.estado = 'generating';

      window.pywebview.api.generar_voz(texto).then(function(b64){
        if(!b64){
          btn.textContent = '▶';
          btn.disabled = false;
          btn.dataset.estado = 'none';
          return;
        }
        // convertimos el base64 a audio reproducible
        var audio = new Audio('data:audio/wav;base64,' + b64);
        btn._audio = audio;
        btn._pauseTimeout = null;
        btn.disabled = false;
        btn.textContent = '▶';
        btn.dataset.estado = 'ready';

        audio.onended = function(){
          btn.textContent = '▶';
          btn.dataset.estado = 'ready';
          if(btn._pauseTimeout) clearTimeout(btn._pauseTimeout);
          modo = 'reposo';
        };

        // arrancamos a reproducir de una
        audio.play();
        btn.textContent = '⏸';
        btn.dataset.estado = 'playing';
        modo = 'hablando'; // la presencia reacciona mientras habla
      });
      return;
    }

    var audio = btn._audio;
    if(!audio) return;

    if(btn.dataset.estado === 'playing'){
      // pausar
      audio.pause();
      btn.textContent = '▶';
      btn.dataset.estado = 'paused';
      modo = 'reposo';
      // si no le dan play en 15s, se resetea
      btn._pauseTimeout = setTimeout(function(){
        audio.pause();
        audio.currentTime = 0;
        btn.textContent = '▶';
        btn.dataset.estado = 'ready';
      }, 15000);

    } else if(btn.dataset.estado === 'paused'){
      // reanudar
      if(btn._pauseTimeout){ clearTimeout(btn._pauseTimeout); btn._pauseTimeout = null; }
      audio.play();
      btn.textContent = '⏸';
      btn.dataset.estado = 'playing';
      modo = 'hablando';

    } else if(btn.dataset.estado === 'ready'){
      // reproducir de nuevo desde cero
      audio.play();
      btn.textContent = '⏸';
      btn.dataset.estado = 'playing';
      modo = 'hablando';
    }
  }

  // --- Micrófono (toggle: apretar para grabar, apretar/Enter para parar) ---
  var btnMic = document.getElementById('btn-mic');
  var grabando = false;

  function toggleMicrofono(){
    if(!(window.pywebview && window.pywebview.api)) return;

    if(!grabando){
      // empezar a grabar
      window.pywebview.api.iniciar_microfono().then(function(ok){
        if(ok){
          grabando = true;
          btnMic.classList.add('grabando');
        }
      });
    } else {
      // parar y transcribir
      grabando = false;
      btnMic.classList.remove('grabando');
      btnMic.textContent = '…';
      btnMic.disabled = true;

      window.pywebview.api.detener_microfono().then(function(texto){
        btnMic.textContent = '●';
        btnMic.disabled = false;
        if(texto){
          // el texto transcrito CAE en el input, editable, NO se envía
          if(inputChat.value.trim()){
            inputChat.value = inputChat.value.trim() + ' ' + texto;
          } else {
            inputChat.value = texto;
          }
          ajustarAltura();
          inputChat.focus();
        }
      });
    }
  }

  // El textarea crece con el texto
  function ajustarAltura(){
    inputChat.style.height = 'auto';
    inputChat.style.height = Math.min(inputChat.scrollHeight, 200) + 'px';
  }

  
  inputChat.addEventListener('input', ajustarAltura);

  btnMic.addEventListener('click', toggleMicrofono);

  // Enter mientras grabás también detiene (además de enviar cuando no grabás)
  inputChat.addEventListener('keydown', function(e){
    if(e.key === 'Enter' && !e.shiftKey){
      e.preventDefault();
      if(grabando){
        toggleMicrofono();  // si estás grabando, Enter detiene
      } else {
        enviarMensaje();    // si no, Enter envía
      }
    }
    // Shift+Enter hace salto de línea normal (no hacemos nada, comportamiento default)
  });

  // --- Modo manos libres ---
  var btnML = document.getElementById('btn-manoslibres');
  var manosLibresActivo = false;

  btnML.addEventListener('click', function(){
    if(!(window.pywebview && window.pywebview.api)) return;

    if(!manosLibresActivo){
      window.pywebview.api.iniciar_manos_libres().then(function(ok){
        if(ok){
          manosLibresActivo = true;
          btnML.classList.add('activo');
          escenario.classList.add('manoslibres');
          modo = 'reposo';  // la presencia queda atenta
        }
      });
    } else {
      window.pywebview.api.detener_manos_libres().then(function(){
        manosLibresActivo = false;
        btnML.classList.remove('activo');
        escenario.classList.remove('manoslibres');
      });
    }
  });

  // Esta función la llama el hilo de Python cuando transcribe tu voz
  window.recibirVozManosLibres = function(texto){
    if(!texto) return;
    // mostramos tu mensaje en el chat
    agregarMensaje(texto, 'user');
    modo = 'hablando';  // la presencia se activa: Bridget va a procesar

    // pedimos la respuesta al cerebro
    window.pywebview.api.enviar_mensaje(texto).then(function(respuesta){
      agregarMensaje(respuesta, 'bridget');
      // Bridget habla la respuesta (esto pausa la escucha mientras suena)
      window.pywebview.api.hablar_respuesta(respuesta).then(function(){
        modo = 'reposo';  // terminó de hablar, vuelve a escuchar
      });
    });
  };

})();