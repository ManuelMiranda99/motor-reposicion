# Decisiones técnicas y de producto

Cada decisión registra el contexto, las alternativas consideradas, la decisión tomada y su
justificación. Las decisiones sobre disponibilidad de la información en el tiempo, validación de datos
y manejo de correcciones se desarrollarán en las fases 2 y 3.

## Índice

| # | Decisión | Estado |
|---|---|---|
| 1 | Cadencia semanal y horizonte de 14 días | Aceptada |
| 2 | Remoto DVC en DagsHub | Aceptada |
| 3 | Gestión de dependencias con pip + venv | Aceptada |
| 4 | Flujo Git: `main` protegida, ramas y PRs con CI | Aceptada |
| 5 | Disponibilidad de la información en el tiempo (as-of) | Pendiente |
| 6 | Validación de datos: reglas duras vs. blandas | Pendiente |
| 7 | Manejo de correcciones | Pendiente |
| 8 | Modelos, validación temporal y métricas | Pendiente |
| 9 | Pedido sugerido (newsvendor) | Pendiente |
| 10 | Criterio de reemplazo de modelo | Pendiente |
| 11 | Versionado de publicaciones desde Airflow | Pendiente |

---

## 1. Cadencia semanal y horizonte de 14 días

- **Contexto:** operaciones pide una sugerencia de pedido cada semana. El enunciado deja el horizonte
  a criterio del equipo.
- **Alternativas:** horizonte de 7 días (solo la semana del pedido); 16 días (igual que Kaggle).
- **Decisión:** corte cada lunes y pronóstico diario de los 14 días siguientes.
- **Justificación:** el pedido cubre 7 días, y los 7 restantes dan margen para un lead time
  configurable y para ver la semana siguiente sin cambiar el modelo.

## 2. Remoto DVC en DagsHub

- **Contexto:** el remoto tiene que ser compartido y el equipo docente debe poder hacer `dvc pull`.
- **Alternativas:** S3/GCS (credenciales y costo), Google Drive (OAuth frágil para terceros).
- **Decisión:** DagsHub como remoto S3-compatible (`s3://dvc` con endpoint
  `https://dagshub.com/ManuelMiranda99/motor-reposicion.s3`) ligado al repo de GitHub. Las
  credenciales van solo en `.dvc/config.local` (fuera de git) y se configuran con
  `tools/dvc_auth.sh`.
- **Justificación:** es gratuito, se integra con el repo de GitHub y la autenticación es un solo token.
- **Limitación encontrada:** DagsHub exige iniciar sesión para cualquier acceso, incluso de lectura a
  repos públicos. Se probó `dvc pull` anónimo desde un clon limpio, por S3 (con
  `allow_anonymous_login`) y por HTTP (`.dvc`), y ambos devuelven 401. Por eso quien evalúe necesita
  una cuenta gratuita de DagsHub y su propio token. Como el repo es público, ese token le da lectura;
  no hace falta invitarlo como colaborador.
- **Alternativa descartada:** un bucket S3/R2 con lectura pública permitiría `dvc pull` sin cuenta,
  pero exige una cuenta cloud con tarjeta y administrar políticas del bucket. Se descartó para
  mantener la infraestructura mínima.

## 3. Gestión de dependencias con pip + venv

- **Contexto:** se necesita el mismo entorno en local, en CI y en la imagen de Airflow, sin modificar
  el Python global.
- **Alternativas:** uv, Poetry.
- **Decisión:** `python -m venv .venv` con `requirements.txt` (runtime) y `requirements-dev.txt`
  (desarrollo), ambos con versiones fijadas con `==`. `dvc[s3]` va en runtime porque Airflow lo usa
  para versionar las publicaciones.
- **Justificación:** es el estándar más simple y la imagen de Airflow lo consume directamente
  (`pip install -r requirements.txt`). Las versiones fijadas dan reproducibilidad.

## 4. Flujo Git: `main` protegida, ramas y PRs con CI

- **Contexto:** el enunciado exige trabajo con ramas y PRs, la rama principal protegida y pytest en
  cada PR.
- **Decisión:** `main` exige PR con el check `lint-y-pruebas` en verde y no permite force-push ni
  borrado. Como el proyecto es individual, no se exige aprobación de otra persona.
- **Justificación:** garantiza que todo cambio en `main` pasó las pruebas automatizadas.
