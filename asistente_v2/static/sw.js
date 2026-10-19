// Service worker de Bridget: cachea el "caparazón" de la app (HTML, CSS, JS,
// íconos) para que abra al instante en el celular. Estrategia red-primero:
// si hay conexión siempre se sirve lo último (nada de versiones viejas tras
// una actualización); la caché solo entra cuando no hay red. Las llamadas a
// la API (chat, audio, agenda...) NUNCA se cachean.

const CACHE = "bridget-v1";
const SHELL = [
    "/",
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/icono-192.png",
    "/static/icono-512.png",
    "/manifest.json",
];

self.addEventListener("install", (e) => {
    e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
    self.skipWaiting();
});

self.addEventListener("activate", (e) => {
    // limpiar cachés de versiones anteriores
    e.waitUntil(
        caches.keys().then((claves) =>
            Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (e) => {
    const url = new URL(e.request.url);
    const esShell = e.request.method === "GET" &&
        (SHELL.includes(url.pathname) || url.pathname.startsWith("/static/"));
    if (!esShell) return; // API: directo a la red, sin tocar

    e.respondWith(
        fetch(e.request)
            .then((res) => {
                const copia = res.clone();
                caches.open(CACHE).then((c) => c.put(e.request, copia));
                return res;
            })
            .catch(() => caches.match(e.request))
    );
});

// --- Notificaciones push ---
self.addEventListener("push", (e) => {
    let datos = { titulo: "Bridget", cuerpo: "Tenés una notificación." };
    try {
        datos = e.data.json();
    } catch (err) {
        // si por algo no viene JSON, usamos el default de arriba
    }
    e.waitUntil(
        self.registration.showNotification(datos.titulo || "Bridget", {
            body: datos.cuerpo || "",
            icon: "/static/icono-192.png",
            badge: "/static/icono-192.png",
        })
    );
});

// Al tocar la notificación, abre (o enfoca) Bridget
self.addEventListener("notificationclick", (e) => {
    e.notification.close();
    e.waitUntil(
        clients.matchAll({ type: "window" }).then((lista) => {
            for (const cliente of lista) {
                if ("focus" in cliente) return cliente.focus();
            }
            if (clients.openWindow) return clients.openWindow("/");
        })
    );
});