# 🚀 Guía Práctica: Cómo Subir Tus Cambios a GitHub
**Manual para Desarrolladores – Centro Nodo**

Esta guía te explica de forma muy sencilla cómo guardar y subir a GitHub cualquier cambio que realices en el proyecto, **sin importar si es grande o un ajuste de una sola línea**.

---

## 📌 Los Dos Repositorios Configurados

En tu equipo tienes vinculados dos destinos en GitHub:

1. **`c4rlosv1`** (Repositorio del proyecto del equipo):  
   `https://github.com/c4rlosv1/Centro_Nodo.git`
2. **`origin`** (Tu repositorio de respaldo personal):  
   `https://github.com/negrosson/GESTION-NODO.git`

---

## 💻 Opción A: Desde la Terminal (Recomendada)

Abre la terminal en la carpeta del proyecto (`X:\Datos Proyectos\centro nodo`) y sigue siempre estos **4 pasos**:

### Paso 1: Revisar qué archivos modificaste
```powershell
git status
```
* Verás en **rojo** los archivos que editaste o creaste. Esto te permite verificar que solo estás subiendo lo que realmente quieres guardar.

### Paso 2: Preparar los archivos para el guardado (Stage)
```powershell
git add .
```
* El punto `.` significa *"preparar todos los archivos modificados en esta carpeta"*.
* Si solo quieres subir un archivo específico: `git add clinica/models.py`.
* Si vuelves a ejecutar `git status`, ahora los archivos aparecerán en **verde**.

### Paso 3: Crear el punto de guardado (Commit)
Escribe un mensaje breve y claro entre comillas que describa lo que hiciste:
```powershell
git commit -m "Ajuste en el formulario de login"
```
* Otros ejemplos de mensajes claros:
  * `git commit -m "docs: corregir diagrama ER y agregar tabla atencion clinica"`
  * `git commit -m "fix: corregir error en redireccion de logout"`
  * `git commit -m "style: cambiar color de botones en el dashboard"`

### Paso 4: Subir los cambios a GitHub (Push)
Para enviar los cambios al repositorio compartido:
```powershell
git push c4rlosv1 main
```
Y si también quieres tenerlos actualizados en tu GitHub personal:
```powershell
git push origin main
```

---

## ⚡ TRUCO PRO: Subir a los dos repositorios en 1 solo comando

Podemos configurar Git para que al escribir simplemente `git push` se envíe a ambos lugares al mismo tiempo:

```powershell
# Esto ya está listo para configurarse:
git remote set-url --add --push origin https://github.com/negrosson/GESTION-NODO.git
git remote set-url --add --push origin https://github.com/c4rlosv1/Centro_Nodo.git
```
Con eso, la próxima vez solo escribirás:
```powershell
git add .
git commit -m "tu mensaje aquí"
git push
```
¡Y se subirá a ambos repositorios automáticamente!

---

## 🖱️ Opción B: Desde la Interfaz Gráfica de VS Code

Si no quieres usar la terminal, puedes hacerlo 100% con clics en VS Code:

1. **Abre la pestaña de Control de Código Fuente:**
   * Haz clic en el ícono de las tres ramificaciones en la barra lateral izquierda (o presiona `Ctrl + Shift + G`).
2. **Revisar cambios:**
   * En la sección **"Cambios"** (Changes), verás los archivos que modificaste.
3. **Preparar archivos (`git add`):**
   * Pasa el ratón sobre la palabra **"Cambios"** y haz clic en el símbolo **`+`** (Stage All Changes). Todos los archivos pasarán a *"Cambios preparados"*.
4. **Hacer el Commit:**
   * En la caja de texto que dice *"Mensaje"*, escribe lo que hiciste (ej. *"Cambiar título de la página"*).
   * Haz clic en el botón azul **"Confirmar"** (Commit).
5. **Subir a GitHub (`git push`):**
   * Haz clic en el botón azul **"Sincronizar cambios"** (Sync Changes) o en los tres puntitos `...` > **Empujar** (Push).

---

## ❓ Preguntas Frecuentes y Qué Hacer ante Errores

### ¿Qué pasa si mi compañero subió cambios antes que yo?
Si al hacer `git push` la terminal dice `[rejected] non-fast-forward`, significa que hay cambios nuevos en GitHub que aún no tienes en tu máquina.
Solo debes descargarlos primero:
```powershell
git pull c4rlosv1 main
```
Luego vuelve a ejecutar tu `git push`.

### ¿Se subirán mis contraseñas o mi base de datos SQLite?
**No.** El archivo `.gitignore` ya está configurado para proteger tu archivo `.env` (credenciales privadas) y `db.sqlite3` (base de datos local de pruebas), por lo que nunca se subirán por accidente.

