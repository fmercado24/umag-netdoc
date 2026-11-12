# Guía: instalar NetDoc en un servidor Ubuntu

Para el personal de la DSI que deje NetDoc corriendo en un servidor. Al terminar queda
un servicio que arranca solo, atiende por HTTPS y se administra con el comando `netdoc`.
Para trabajar en un equipo propio no hace falta nada de esto: basta `./iniciar.sh`.

## Resumen

```bash
git clone https://github.com/fmercado24/umag-netdoc.git     # o copie la carpeta (sección 4.1)
cd umag-netdoc
sudo ./instalar-servidor.sh                                 # pregunta la base y la contraseña
sudo netdoc estado                                          # debe decir active (running)
```

Abra `https://<ip-del-servidor>` e ingrese con `admin-netdoc` y la contraseña que definió.

## 1. Qué queda instalado

```mermaid
flowchart LR
    N[Navegador] -- "HTTPS 443" --> X[nginx]
    M[Prometheus, Alertmanager, Zabbix] -- "HTTPS 8000" --> X
    X -- "127.0.0.1:8001" --> A["Servicio netdoc<br/>usuario netdoc"]
    A --> B[("SQLite o PostgreSQL")]
    A --> F["Planos y fotografías"]
```

| Dónde | Qué | Quién puede modificarlo |
|---|---|---|
| `/opt/netdoc` | Código, entorno de Python y visor compilado | Solo root: el servicio no puede modificarse a sí mismo |
| `/var/lib/netdoc` | Base SQLite, `media/` (planos, teselas, fotos) y `respaldos/` | El usuario `netdoc`; los respaldos, solo root |
| `/etc/netdoc/netdoc.env` | Configuración, con la URL de la base y el hash de la contraseña | Solo root |
| `/etc/netdoc/tls/` | Certificado y clave de HTTPS | Solo root |
| `/etc/systemd/system/netdoc.service` | El servicio. Corre como `netdoc`, sin privilegios y con el resto del sistema en solo lectura | Lo reescribe el instalador |
| `/etc/nginx/sites-available/netdoc` | HTTPS y reenvío a la API | Lo reescribe el instalador |
| `/usr/local/bin/netdoc` | El comando de administración (sección 7) | Lo reescribe el instalador |

## 2. Requisitos

| | Mínimo | Comentario |
|---|---|---|
| Sistema | Ubuntu Server **24.04 o 26.04 LTS** | 22.04 no sirve: su Python es 3.10 y NetDoc requiere 3.11 o superior |
| Permisos | Un usuario con `sudo` | NetDoc en sí corre con su propio usuario, sin privilegios |
| Memoria | **4 GB** | En uso normal ocupa poco (la API, unos 100 MB), pero al dibujar cada lámina un proceso llega a 1 GB. Es lo que se probó; con menos, agregue memoria de intercambio |
| Disco | **10 GB** libres | NetDoc y el CADI ocupan unos 500 MB, y cada respaldo, unos 200 MB (se guardan 14). Suma lo que traigan otros edificios |
| Internet | Durante la instalación y al actualizar | Para `apt`, PyPI y npm; en Ubuntu 24.04, también nodejs.org. Después no lo necesita |
| Red | Puertos 80 y 443 hacia los usuarios | El 8000, solo si usa monitoreo (sección 11) |

## 3. Elegir la base de datos

| | SQLite | PostgreSQL |
|---|---|---|
| Qué es | Un archivo, `/var/lib/netdoc/netdoc.db` | Un servicio aparte, en este servidor o en otro |
| Instalación | Nada adicional | El instalador lo instala y crea su usuario, contraseña y base |
| Respaldo | `sudo netdoc respaldar` | `sudo netdoc respaldar`, o las herramientas que ya use la DSI |
| Conviene si | Un solo servidor y pocas personas editando a la vez, como en NetDoc | La DSI ya administra PostgreSQL, o la base debe estar en otro servidor o crecer con más procesos |

Para NetDoc, con unos pocos usuarios, **SQLite alcanza**, y es lo más simple de operar.
La elección no es definitiva (sección 10.2).

## 4. Instalar

### 4.1 Llevar el código al servidor

Con acceso al repositorio, clónelo. Como es privado, GitHub pedirá autenticarse con un
[token](https://docs.github.com/es/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
o una clave SSH:

```bash
git clone https://github.com/fmercado24/umag-netdoc.git
cd umag-netdoc
```

Sin acceso desde el servidor, cópielo desde otro equipo. No copie `.env`: tiene el hash de
la contraseña de ese equipo.

```bash
rsync -av --exclude .git --exclude node_modules --exclude .venv --exclude dist \
  --exclude 'backend/media' --exclude '*.db' --exclude .env --exclude '*.log' \
  umag-netdoc/ usuario@servidor:umag-netdoc/
```

### 4.2 Ejecutar el instalador

```bash
cd umag-netdoc
sudo ./instalar-servidor.sh
```

Pregunta dos cosas, y lo demás lo hace solo:

1. **La base de datos** (sección 3), salvo que la indique con `--base`.
2. **La contraseña del administrador**, `admin-netdoc`. Pide al menos 8 caracteres y avisa
   si son menos de 15, que es lo recomendado. No queda en ningún archivo: solo su hash, en
   `/etc/netdoc/netdoc.env`.

La primera vez dibuja las láminas, y eso es lo que más tarda: de 5 a 20 segundos por lámina
en un equipo normal, de modo que en total cuente con unos 10 a 15 minutos. Al final comprueba
que el servicio responda y exija sesión, y muestra la dirección.

### 4.3 Opciones

| Opción | Para qué |
|---|---|
| `--base sqlite` | No pregunta: usa SQLite |
| `--base postgresql` | No pregunta: instala PostgreSQL en este servidor |
| `--postgres-url URL` | Usa un PostgreSQL existente, sin instalar uno: `postgresql+psycopg://usuario:clave@servidor:5432/base`. La base y el usuario deben existir, y el usuario debe poder crear tablas en ella |
| `--dominio NOMBRE` | El nombre con que se accede, como `netdoc.umag.cl`. Se recuerda en las actualizaciones |
| `--certificado ARCHIVO`, `--clave-certificado ARCHIVO` | Certificado propio en vez de uno autofirmado (sección 5) |
| `--cambiar-base` | Pasa los datos a la base indicada (sección 10.2) |

Por ejemplo:

```bash
sudo ./instalar-servidor.sh --base postgresql --dominio netdoc.umag.cl \
  --certificado /ruta/netdoc.crt --clave-certificado /ruta/netdoc.key
```

### 4.4 Comprobar

```bash
sudo netdoc estado     # active (running) y {"estado":"ok","base_datos":"ok"}
```

Abra `https://<ip-del-servidor>` e ingrese. Con el certificado autofirmado el navegador
mostrará una advertencia la primera vez; es lo esperado (sección 5). Debe ver el CADI con
sus planos. Después de reiniciar el servidor, NetDoc vuelve a levantarse solo.

## 5. Certificado HTTPS

Sin indicar nada, el instalador genera un certificado **autofirmado** para el nombre y las
IP del servidor, válido por 397 días. Cifra la conexión, pero el navegador no puede
comprobar que el servidor sea el verdadero, y por eso advierte. Sirve para empezar y para
una red de pruebas; se renueva solo al actualizar si le quedan menos de 30 días.

**Para producción, use un certificado de la institución.** Debe incluir el nombre con que
se accede y, en el mismo archivo, la cadena intermedia:

```bash
sudo ./instalar-servidor.sh --dominio netdoc.umag.cl \
  --certificado /ruta/netdoc.crt --clave-certificado /ruta/netdoc.key
```

Se copian a `/etc/netdoc/tls/`, así que después puede borrar los originales. Para renovarlo,
vuelva a ejecutar el mismo comando con los archivos nuevos.

**Con Let's Encrypt**, si el servidor tiene un nombre público y recibe conexiones por el
puerto 80 desde Internet. Los dos ganchos quedan guardados: en cada renovación, certbot detiene
nginx para usar el puerto 80 y luego lo vuelve a levantar, ya con el certificado nuevo.

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d netdoc.umag.cl \
  --pre-hook 'systemctl stop nginx' --post-hook 'systemctl start nginx'
sudo ./instalar-servidor.sh --dominio netdoc.umag.cl \
  --certificado /etc/letsencrypt/live/netdoc.umag.cl/fullchain.pem \
  --clave-certificado /etc/letsencrypt/live/netdoc.umag.cl/privkey.pem
```

Esas rutas no se copian, para que tome las renovaciones.

## 6. Firewall

Si `ufw` está activo, el instalador abre los puertos 80 y 443. Si no está activo, puede
activarlo, **cuidando de no cortar su propio acceso por SSH**:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

La API (8001), PostgreSQL (5432) y lo que publica `docker-compose.yml` escuchan solo en el
propio servidor: no hay que abrirlos.

## 7. Administrar

| Comando | Qué hace |
|---|---|
| `sudo netdoc estado` | Si el servicio corre y responde |
| `sudo netdoc registro` | Lo que informa, en vivo: peticiones, ingresos, intentos fallidos, errores |
| `sudo netdoc reiniciar` | Reinicia el servicio |
| `sudo netdoc clave` | Cambia la contraseña, cierra las sesiones y reinicia |
| `sudo netdoc usuario` | Lista los demás usuarios |
| `sudo netdoc usuario agregar NOMBRE [--edificio CADI] [--generar]` | Crea otro usuario, si se quiere limitado a un edificio, y reinicia ([detalle](seguridad.md#otros-usuarios)) |
| `sudo netdoc usuario clave NOMBRE`, `… quitar NOMBRE` | Cambia su contraseña o lo elimina, cierra sus sesiones y reinicia |
| `sudo netdoc desbloquear` | Levanta el bloqueo por intentos de ingreso fallidos |
| `sudo netdoc importar` | Carga lo nuevo de `/opt/netdoc/data/` (ver sección 8) |
| `sudo netdoc respaldar` | Respalda la base y los archivos |
| `sudo netdoc restaurar ARCHIVO` | Vuelve a un respaldo |
| `sudo netdoc traer-datos BASE.db [MEDIA]` | Trae los datos de otro equipo (sección 10.1) |

La configuración está en `/etc/netdoc/netdoc.env`; las variables disponibles, en
`/opt/netdoc/.env.example`. Después de cambiarla, `sudo netdoc reiniciar`. La contraseña, los
bloqueos, las sesiones y los tokens se explican en [seguridad.md](seguridad.md).

## 8. Actualizar

En la carpeta del repositorio:

```bash
git pull
sudo ./instalar-servidor.sh
```

Es el mismo comando: como ya está instalado, no pregunta nada. **Primero respalda**, luego
copia el código, instala lo que cambió, aplica las migraciones e importa lo nuevo de `data/`,
y reinicia. Conserva la base, la contraseña y los certificados. NetDoc deja de responder solo
durante las migraciones y el reinicio.

Para incorporar un edificio nuevo, siga la [guía de edificios](guia-nuevo-edificio.md), súbalo
al repositorio y actualice de esta misma forma. Importa solo lo que aún no tiene elementos:
nunca reemplaza lo existente, incluido lo que se haya agregado desde el visor.

## 9. Respaldos

```bash
sudo netdoc respaldar                 # en /var/lib/netdoc/respaldos; conserva los últimos 14
sudo netdoc respaldar /mnt/respaldos  # en otra carpeta; ahí no borra ninguno
```

Cada respaldo es un `.tar.gz` con la base, los planos y fotos, y la configuración. Se puede
hacer con el servicio corriendo. **Contiene el hash de la contraseña y las claves de la base:
guárdelo como un secreto.**

Para hacerlo todas las noches, a las 02:30:

```bash
echo '30 2 * * * root /usr/local/bin/netdoc respaldar' | sudo tee /etc/cron.d/netdoc-respaldo
```

**Un respaldo en el mismo disco no protege de perder el servidor.** Cópielos a otro equipo,
por ejemplo desde este, con un usuario que pueda leerlos:

```bash
rsync -a usuario@servidor:/var/lib/netdoc/respaldos/ /ruta/segura/netdoc/
```

Para volver a uno. Respalda antes lo actual, por si fue un error:

```bash
sudo netdoc restaurar /var/lib/netdoc/respaldos/netdoc-20261103-023000.tar.gz
```

Restaura la base y los archivos, no la configuración: la contraseña sigue siendo la actual.
Se puede restaurar un respaldo de SQLite en una instalación con PostgreSQL, pero no al revés.
Pruebe restaurar de vez en cuando, en otro servidor: un respaldo que nunca se restauró no es
una garantía.

## 10. Datos existentes

### 10.1 Traer lo que ya tiene en otro equipo

Una instalación nueva carga el CADI desde las planillas de `data/`. Si ya trabajó en otro
equipo con `./iniciar.sh` (ubicó elementos, agregó otros, completó fichas), puede traer esos
datos, para cualquiera de las dos bases. Detenga NetDoc en ese equipo y copie al servidor su
base y sus archivos:

```bash
# En el otro equipo, con NetDoc detenido
rsync -av umag-netdoc/backend/umag_netdoc.db umag-netdoc/backend/media usuario@servidor:traer/

# En el servidor
sudo netdoc traer-datos ~/traer/umag_netdoc.db ~/traer/media
```

Reemplaza lo que hay en el servidor, habiéndolo respaldado antes.

### 10.2 Cambiar de base

```bash
sudo ./instalar-servidor.sh --base postgresql --cambiar-base      # instala PostgreSQL
sudo ./instalar-servidor.sh --postgres-url 'postgresql+psycopg://…' --cambiar-base   # uno existente
sudo ./instalar-servidor.sh --base sqlite --cambiar-base          # de vuelta a SQLite
```

Respalda, prepara la base nueva, copia los datos en una sola transacción y cambia la
configuración. Si algo falla, la base anterior sigue siendo la vigente. Al pasar desde SQLite,
el archivo anterior queda en su lugar: bórrelo cuando confirme que todo está bien. Las
sesiones no se copian, así que habrá que volver a ingresar.

## 11. Monitoreo

Prometheus, Alertmanager y Grafana se levantan como indica el
[manual de monitoreo](manual-monitoreo.md), con estas diferencias:

- NetDoc ya atiende en la red: **omita** el paso de `NETDOC_API_HOST=0.0.0.0 ./iniciar.sh`.
- El instalador deja el certificado donde lo busca `docker-compose.yml`.
- `NETDOC_MONITOREO_TOKEN` y `NETDOC_GRAFANA_CLAVE` van en `/etc/netdoc/netdoc.env`, y luego
  `sudo netdoc reiniciar`.
- Con `ufw` activo, permita que los contenedores lleguen al puerto 8000.

```bash
sudo ufw allow from 172.16.0.0/12 to any port 8000 proto tcp
cd /opt/netdoc
sudo docker compose --env-file /etc/netdoc/netdoc.env --profile monitoreo up -d
```

Zabbix usa `https://<servidor>:8000/api/v1/integraciones/monitoreo/estado` como `netdoc_url`.

## 12. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `este script instala servicios del sistema: ejecútalo con sudo` | Se ejecutó sin `sudo` | `sudo ./instalar-servidor.sh` |
| `se requiere Python 3.11 o superior` | Ubuntu 22.04 o anterior | Use Ubuntu 24.04 o posterior |
| `sin terminal no puedo preguntar` | Se ejecutó por un sistema automático | Indique `--base`, y defina la contraseña antes en una terminal |
| `esta instalación ya usa … para pasarlos a la nueva base` | Se pidió otra base sobre una instalación con datos | Agregue `--cambiar-base` (sección 10.2) |
| `el certificado y la clave no corresponden entre sí` | Archivos equivocados | Revise que la clave sea la de ese certificado |
| El navegador advierte sobre el certificado | Es autofirmado | Normal; en producción, sección 5 |
| El navegador advierte *nombre no coincide* | Se accede con un nombre que el certificado no incluye | Instale con `--dominio`; si el autofirmado ya existe, borre `/etc/netdoc/tls/netdoc.*` antes |
| `502 Bad Gateway` | nginx corre, pero el servicio no | `sudo netdoc estado` y `sudo netdoc registro` |
| No carga desde otro equipo | Firewall del servidor o de la red | Sección 6; pruebe `curl -k https://<ip>` desde otro equipo |
| `413` al cargar una lámina | Supera los 100 MB | Suba `NETDOC_CARGA_MAX_MB` y `client_max_body_size` en la configuración de nginx (la actualización lo reescribe) |
| `Demasiados intentos fallidos` | Tres contraseñas incorrectas desde ese equipo | Espere 15 minutos o `sudo netdoc desbloquear` |
| Olvidó la contraseña | | `sudo netdoc clave` |
| El servicio no arranca tras cambiar la configuración | Valor inválido en `/etc/netdoc/netdoc.env` | `sudo netdoc registro`; corrija el valor |
| `No se pudo cargar NetDoc`, *No hay conexión* en el visor | El servicio se detuvo | `sudo netdoc estado`; `sudo netdoc reiniciar` |

## 13. Desinstalar

Antes, haga un respaldo y cópielo fuera del servidor. Esto **borra los datos de NetDoc**:

```bash
sudo systemctl disable --now netdoc
sudo rm -f /etc/systemd/system/netdoc.service /etc/nginx/sites-enabled/netdoc /etc/nginx/sites-available/netdoc /usr/local/bin/netdoc /etc/cron.d/netdoc-respaldo
sudo systemctl daemon-reload
sudo systemctl reload nginx
sudo rm -rf /opt/netdoc /etc/netdoc /var/lib/netdoc
sudo userdel netdoc

# Si usó el PostgreSQL de este servidor
sudo -u postgres dropdb umag_netdoc
sudo -u postgres dropuser netdoc
```

Los paquetes del sistema (`nginx`, `postgresql`, Node.js) quedan instalados, por si otro
servicio los usa.

## Qué se probó

Con `instalar-servidor.sh` real, en máquinas virtuales recién creadas:

| | Ubuntu Server 24.04 | Ubuntu Server 26.04 |
|---|---|---|
| Base | PostgreSQL 16 | SQLite |
| Paquetes | nginx 1.24, Node oficial (el de `apt` es muy antiguo), Python 3.12 | nginx 1.28, Node de `apt`, Python 3.14 |

En ellas se comprobó la instalación, retomar una instalación interrumpida, actualizar, el
ingreso y el alta de elementos con un navegador por HTTPS, el bloqueo por intentos, el
reinicio del servidor, respaldar y restaurar, traer datos de otro equipo, cambiar de base en
ambos sentidos, certificado propio con dominio y desinstalar. Además, las pruebas automáticas
pasaron contra PostgreSQL 16 en esas máquinas. Trasladar, eliminar y restaurar se agregaron
después: todas las pruebas pasan contra PostgreSQL 18 y se recorrieron con un navegador sobre
SQLite, pero no en estas máquinas virtuales. Lo mismo vale para `sudo netdoc usuario`: el
programa que administra los usuarios tiene pruebas automáticas, pero el comando no se corrió
en un servidor.

**No se probó:** el perfil de monitoreo con contenedores reales (sección 11): se reprodujeron
sus peticiones contra el puerto 8000, con su token y certificado, pero no con Docker,
Prometheus ni Alertmanager. Tampoco Let's Encrypt, que requiere un nombre público, ni Zabbix,
ni un PostgreSQL en otro servidor (`--postgres-url`). Los tiempos son estimados: las máquinas
virtuales eran emuladas, mucho más lentas que un servidor real.
