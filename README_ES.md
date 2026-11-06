> Creado en China. Al igual que los equipos detrás de [Deepseek] y [Black Myth: Wukong], esperamos aportar más belleza al mundo.

<img src="https://dataelem.com/bs/face.png" alt="Bisheng banner">

<p align="center">
    <a href="https://dataelem.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"><img src="https://img.shields.io/badge/docs-Wiki-brightgreen"></a>
    <img src="https://img.shields.io/github/license/dataelement/bisheng" alt="license"/>
    <img src="https://img.shields.io/docker/pulls/dataelement/bisheng-frontend" alt="docker-pull-count" />
    <a href=""><img src="https://img.shields.io/github/last-commit/dataelement/bisheng"></a>
    <a href="https://star-history.com/#dataelement/bisheng&Timeline"><img src="https://img.shields.io/github/stars/dataelement/bisheng?color=yellow"></a>
</p>
<p align="center">
  <a href="./README.md">简体中文</a> |
  <a href="./README_EN.md">English</a> |
  <a href="./README_JPN.md">日本語</a> |
  <a href="./README_ES.md">Español</a> |
  <a href="./README_PT.md">Português</a> |
  <a href="./README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/717" target="_blank"><img src="https://trendshift.io/api/badge/repositories/717" alt="dataelement%2Fbisheng | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>
<div class="column" align="middle">
  <!-- <a href="https://bisheng.slack.com/join/shared_invite/"> -->
    <!-- <img src="https://img.shields.io/badge/Join-Slack-orange" alt="join-slack"/> -->
  </a>
  <!-- <img src="https://img.shields.io/github/license/bisheng-io/bisheng" alt="license"/> -->
  <!-- <img src="https://img.shields.io/docker/pulls/bisheng-io/bisheng" alt="docker-pull-count" /> -->
</div>


BISHENG es una **plataforma empresarial de agentes de código abierto y todo en uno**, centrada en la productividad de oficina y en llevar las aplicaciones de IA empresarial a la práctica. La utilizan organizaciones líderes de distintos sectores y empresas de Fortune 500.

### Gran novedad: llega BISHENG Desktop

BISHENG Desktop está desarrollado sobre DeepSeek Harness (DSH) y funciona junto con la plataforma BISHENG para ofrecer una solución completa de plataforma empresarial de agentes de código abierto, que puede desplegarse de forma privada y mantenerse totalmente bajo su control.

En pocas palabras, puede considerarlo una alternativa de código abierto a WorkBuddy / Doubao Work, que permite a las empresas ser realmente dueñas de sus capacidades de IA y controlarlas.

![Interfaces web, de escritorio y móviles de BISHENG](docs/images/readme/bisheng-platform-overview.png)

[Descargar BISHENG Desktop](https://dshdesktop.com/zh/enterprise/)

Para personalizar el cliente (por ejemplo, sustituir el logotipo), puede modificar el [código abierto del cliente](https://github.com/dataelement/bisheng-desktop).

> El equipo de BISHENG publicó como código abierto un cliente de escritorio para DSH ([dshdesktop.com](https://dshdesktop.com/)) la misma noche en que se lanzó DSH. BISHENG Desktop está desarrollado sobre DSHDesktop. Hasta la fecha, DSHDesktop ha superado las 900.000 descargas y las 17,4 mil estrellas en GitHub ⭐️. Los usuarios particulares pueden utilizar DSHDesktop.
>
> [Sitio web de DSHDesktop](https://dshdesktop.com/zh/)

## Funcionalidades

1. **🖥️ BISHENG Desktop: conecte el trabajo local con la nube de su empresa**

   - **Dos formas de trabajar: Chat y Work**: Chat permite realizar consultas sobre el conocimiento y tareas en la nube de varios pasos. Work organiza los materiales en directorios locales autorizados, genera archivos editables de Word, Excel y PowerPoint y sigue perfeccionándolos a partir de sus comentarios.
   - **Recursos empresariales autorizados según la identidad**: Utilice su cuenta empresarial para acceder a modelos, herramientas API/MCP, habilidades y espacios de conocimiento aprobados, o abra asistentes y flujos de trabajo publicados en el Centro de aplicaciones. La recuperación de conocimiento sigue aplicando los permisos de los espacios y los archivos.
   - **Gestión centralizada de modelos y créditos**: Los administradores gestionan el acceso a los modelos, los créditos mensuales y los registros de llamadas. Las llamadas a modelos empresariales en Chat y Work comparten el registro de créditos del usuario actual; los usuarios pueden consultar su saldo y consumo.
   - **Distribución centralizada de extensiones empresariales**: Los administradores importan complementos y entornos de trabajo de forma centralizada. Los empleados los reciben según la configuración y las autorizaciones de la empresa.

2. **🛠️ Taller de aplicaciones: publique Vibe Apps para su equipo**

   - **Convierta las necesidades de negocio en aplicaciones**: Cree páginas específicas para formularios de inscripción, registros de proyectos o paneles departamentales, y permita que sus compañeros las abran desde el Centro de aplicaciones.
   - **Del desarrollo local al uso en equipo**: Envíe una aplicación desarrollada localmente o con un Coding Agent. Tras las comprobaciones previas, el análisis de secretos, la compilación y la aprobación de la publicación, configure su ámbito de acceso y publíquela en el Centro de aplicaciones.
   - **Reutilice las capacidades de la plataforma**: Las aplicaciones pueden reutilizar el inicio de sesión de la plataforma y la identidad del visitante, y acceder a los modelos y recursos de conocimiento según sea necesario, reduciendo la duplicación de infraestructura. Las capacidades y los requisitos de configuración dependen de la documentación de la versión correspondiente.

   ![Gestión de publicaciones de Vibe Apps en el Taller de aplicaciones de BISHENG](docs/images/readme/bisheng-vibe-app.png)

3. **🚀 Modo de tareas: un agente de propósito general para trabajos complejos de varios pasos**
   Usted le indica un objetivo y, si es necesario, adjunta archivos, bases de conocimiento, herramientas y habilidades. El agente divide el objetivo en tareas, las ejecuta paso a paso y entrega un informe o un archivo de PPT, Excel o Word.

   - 🧠 **Planificación de tareas + subagentes en paralelo**: El agente principal crea una lista de tareas, sigue el progreso y asigna investigaciones independientes a subagentes que se ejecutan en paralelo.
   - 🙋 **Intervención humana**: Cuando el agente necesita información que solo usted conoce, la tarea se pausa hasta que responda.
   - 🧰 **Habilidades listas para usar**: Tres paquetes de habilidades integrados (PPT, Excel y Word) funcionan desde el primer momento. También puede importar las habilidades de su equipo desde un archivo local o desde GitHub.
   - 📎 **Conclusiones trazables**: Los informes incluyen marcadores de cita. Haga clic en un marcador para abrir la fuente e ir al pasaje citado.
   <p align="center"><img src="docs/images/readme/task-mode.png" alt="task-mode"></p>

4. **📚 Espacio de conocimiento: una base de conocimiento empresarial para equipos**

   - 🗂️ **Contenido organizado**: Carpetas de varios niveles, etiquetas, vistas de tarjetas y de lista, y búsqueda combinada por palabra clave y etiqueta.
   - 👥 **Construido en equipo**: Invite a miembros con una plantilla de permisos (Propietario / Gestor / Editor / Lector), o publique el espacio en la Plaza del conocimiento para que otros puedan unirse. Un superadministrador puede crear un Espacio departamental para un departamento en un solo paso.
   - 🔐 **Permisos hasta el nivel de archivo individual**: Los espacios, las carpetas y los archivos utilizan el mismo conjunto de plantillas de permisos. Puede conceder acceso a una persona, a un departamento (incluidos sus subdepartamentos) o a un grupo de usuarios en un solo paso. Las carpetas y los archivos heredan por defecto los permisos de su elemento superior, y también puede configurarlos por separado.
   - 💬 **Preguntas y respuestas con IA**: Haga preguntas sobre un documento o sobre todo el espacio. Las respuestas muestran sus fuentes; haga clic en una fuente para abrir el texto original en el punto citado.
   <p align="center"><img src="docs/images/readme/knowledge-space.png" alt="knowledge-space"></p>

5. **📡 Canales: noticias externas a diario, que se guardan como conocimiento con un solo clic**

   - 📰 **Canales temáticos**: Combine cuentas oficiales de WeChat y sitios web en canales temáticos que se actualizan a diario. Un canal puede tener subcanales.
   - 🎯 **Filtrado preciso**: Las reglas personalizadas filtran los títulos y el cuerpo del texto para conservar únicamente los artículos relevantes.
   <p align="center"><img src="docs/images/readme/channel.png" alt="channel"></p>

6. **🧩 El singular [BISHENG Workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**

   - **Marco de orquestación independiente y completo**: No existe una separación entre chatflow y workflow. La conversación de varios turnos y el procesamiento automatizado pueden coexistir en un mismo flujo.
   - **Intervención humana**: Un flujo en ejecución puede detenerse y esperar a que una persona aporte información, confirme o realice cambios.
   - **Bucles, ramas paralelas y ejecuciones por lotes en cualquier combinación**: Dibuje un círculo para crear un bucle (la mayoría de los productos similares no admiten bucles), coloque nodos uno junto a otro para ejecutarlos en paralelo y seleccione varios elementos para ejecutar un lote. Esto se adapta a escenarios complejos como la revisión de documentos y la generación de informes con diseño fijo.
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="workflow"></p>

7. **🏢 Funcionalidades de nivel empresarial: los controles que necesita la IA empresarial**

   - **Gestión centralizada del cliente de escritorio**: Los administradores configuran de forma centralizada los modelos, las habilidades, las herramientas API/MCP y los espacios de conocimiento disponibles en el cliente, y conceden acceso a los empleados según la configuración empresarial y los permisos de los recursos. El mercado empresarial de complementos distribuye complementos y entornos de trabajo, mientras que los créditos mensuales, el consumo de llamadas y los registros de auditoría se gestionan de forma centralizada.
   - **Gestión de departamentos y usuarios**: Mantenga la estructura organizativa, los usuarios y las cuotas.
   - **Permisos de funciones y recursos separados**: Los roles RBAC controlan los menús de funciones y las acciones. ReBAC controla el acceso a los espacios de conocimiento, las carpetas y los archivos individuales, mediante concesiones a personas, departamentos (incluidos sus subdepartamentos) o grupos de usuarios. Las carpetas y los archivos heredan por defecto los permisos de su elemento superior y también pueden configurarse de forma independiente.
   - **Aprobaciones**: Unirse a un espacio de conocimiento, suscribirse a un canal, solicitar permisos de menú y otras acciones pueden requerir aprobación. Puede personalizar los flujos y los nodos de aprobación.
   - **Auditoría**: Registra el contenido de las conversaciones y los registros de operaciones del sistema, con búsquedas por usuario, fecha y hora y módulo.
   - **Paneles de control** (edición comercial): Paneles preconfigurados para la actividad de los usuarios, el uso de las aplicaciones, el consumo de tokens, el uso de las bases de conocimiento y mucho más.
   - **Límites de permisos de las claves API**: Los administradores emiten claves para cuentas de servicio, establecen su caducidad y los permisos de las interfaces, y conceden acceso a aplicaciones, bases de conocimiento y otros recursos específicos. Los permisos de las interfaces determinan qué acciones están permitidas; las concesiones de recursos determinan dónde se aplican esas acciones. Poseer una clave no concede acceso a toda la plataforma.

     ![Emisión de claves API y configuración de permisos en BISHENG](docs/images/readme/bisheng-api-key.png)

   - **Compatibilidad con Xinchuang (infraestructura informática nacional china)**: Compatible tanto con MySQL como con Dameng DM8.
   - Además: SSO/LDAP, despliegue de alta disponibilidad, revisión de seguridad del contenido, control del tráfico, monitorización y estadísticas, y análisis y corrección de vulnerabilidades.
   <p align="center"><img src="https://dataelem.com/bs/pro.png" alt="enterprise"></p>

   ![Administración empresarial de BISHENG: créditos y consumo del cliente de escritorio](docs/images/readme/bisheng-enterprise-management.png)

8. **🔍 Análisis de documentos de alta precisión**: Nuestros modelos de análisis de documentos se entrenan con una gran cantidad de datos de alta calidad recopilados durante 5 años, y puede desplegarlos de forma privada y gratuita. Incluyen modelos de alta precisión para texto impreso, escritura a mano y caracteres poco frecuentes, reconocimiento de tablas, análisis de diseño y sellos.
   <p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="ocr"></p>


## Inicio rápido

Antes de instalar BISHENG, asegúrese de cumplir los siguientes requisitos:
- CPU >= 8 núcleos
- RAM >= 32 GB
- Docker 19.03.9+
- Docker Compose 1.25.1+
> Además de instalar BISHENG, también instalaremos por defecto los siguientes componentes de terceros: ES, Milvus y Onlyoffice.

Descargar BISHENG
```bash
git clone https://github.com/dataelement/bisheng.git
# Entrar en el directorio de instalación
cd bisheng/docker

# Si el sistema no dispone del comando git, puede descargar el código de BISHENG como archivo zip.
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
# Descomprimir y entrar en el directorio de instalación
unzip main.zip && cd bisheng-main/docker
```
Iniciar BISHENG
```bash
docker compose -f docker-compose.yml -p bisheng up -d
```
Una vez completado el inicio, acceda a http://IP:3001 en el navegador. Aparecerá la página de inicio de sesión; proceda a registrar un usuario.

Por defecto, el primer usuario registrado se convertirá en el administrador del sistema.

Para obtener más información sobre la instalación y el despliegue, consulte: [Alojamiento propio](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)

## Agradecimientos
Este repositorio se beneficia de [langchain](https://github.com/langchain-ai/langchain), [langflow](https://github.com/logspace-ai/langflow), [unstructured](https://github.com/Unstructured-IO/unstructured) y [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory). Gracias por su excelente trabajo.

<b>Gracias a nuestros colaboradores:</b>

<a href="https://github.com/dataelement/bisheng/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dataelement/bisheng" />
</a>



## Comunidad y contacto
Le invitamos a unirse a nuestro grupo de debate

<img src="https://www.dataelem.com/nstatic/qrcode.png" alt="Wechat QR Code">


<!--
## Historial de estrellas

[![Gráfico del historial de estrellas](https://api.star-history.com/svg?repos=dataelement/bisheng&type=Date)](https://star-history.com/#dataelement/bisheng&Date)
-->

## Algunos de nuestros clientes

BISHENG presta servicio a empresas líderes de distintos sectores. Estos son algunos de nuestros clientes.

![Administración Meteorológica de China, HSBC, Bosch, Watsons, China Mobile y COFCO](docs/images/readme/bisheng-customer-logos-row-1.png)

![Shougang Group, China Baowu, CICC, SINOSURE, PetroChina e ICBC](docs/images/readme/bisheng-customer-logos-row-2.png)

![Bank of Chongqing, PowerChina, Huatai Securities, Huaxia Bank, Liaoning Financial Holdings y China Minsheng Bank](docs/images/readme/bisheng-customer-logos-row-3.png)

![Longhua Capital, JSTI, China CITIC Bank, AVIVA-COFCO, BAIC Group y China Bond Rating](docs/images/readme/bisheng-customer-logos-row-4.png)

## Consultas empresariales

Póngase en contacto con nosotros para hablar sobre el despliegue empresarial de BISHENG, la integración del cliente de escritorio, demostraciones del producto o colaboraciones comerciales.

[Contactar con el equipo de BISHENG mediante el formulario de Feishu](https://dataelem.feishu.cn/share/base/form/shrcnVow7GQwwKYEBCD41Bu5qoh)
