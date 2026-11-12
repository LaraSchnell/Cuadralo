-- Cuádralo · prueba de la seguridad por filas. Ejecutar DESPUÉS de 1_activar.sql, en la base de datos de pruebas.
-- No cambia ningún dato: lo que intenta escribir se deshace siempre. Al final enseña una tabla con OK / FALLO.
SET NOCOUNT ON;
DECLARE @r TABLE (n int IDENTITY, prueba nvarchar(200), resultado nvarchar(12), detalle nvarchar(400));
DECLARE @tablas TABLE (nombre sysname);
INSERT @tablas VALUES (N'portal_carga'), (N'portal_interesmodulo'), (N'portal_movimientocontable'), (N'portal_filaoperador'),
                      (N'portal_filapresupuesto'), (N'portal_reserva'), (N'portal_resultadoempresa'), (N'portal_resultadodesviacion');
DECLARE @empresa int, @otra int, @tabla sysname, @sql nvarchar(max), @n int, @esperadas int;

-- 0. La política existe y está encendida.
INSERT @r SELECT N'La política existe y está encendida',
       IIF(EXISTS (SELECT 1 FROM sys.security_policies WHERE name = N'politica_empresa' AND is_enabled = 1), N'OK', N'FALLO'), N'';

-- Empresa con más apuntes y otra empresa cualquiera (la tabla de empresas no lleva la barrera).
EXEC sp_set_session_context @key = N'cuadralo_interno', @value = 1;
EXEC sp_set_session_context @key = N'empresa_id', @value = NULL;
SELECT TOP 1 @empresa = empresa_id FROM dbo.portal_movimientocontable GROUP BY empresa_id ORDER BY COUNT(*) DESC;
SELECT @otra = MIN(id) FROM dbo.portal_empresa WHERE id <> @empresa;
INSERT @r VALUES (N'Hay datos para probar', IIF(@empresa IS NULL, N'FALLO', N'OK'),
                  CONCAT(N'empresa con datos: ', @empresa, N' · otra empresa: ', @otra));

DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT nombre FROM @tablas;
OPEN c; FETCH NEXT FROM c INTO @tabla;
WHILE @@FETCH_STATUS = 0
BEGIN
    -- Cuántas filas tiene de verdad la empresa (modo interno).
    EXEC sp_set_session_context @key = N'cuadralo_interno', @value = 1;
    EXEC sp_set_session_context @key = N'empresa_id', @value = NULL;
    SET @sql = N'SELECT @x = COUNT(*) FROM dbo.' + QUOTENAME(@tabla) + N' WHERE empresa_id = @e';
    EXEC sp_executesql @sql, N'@x int OUTPUT, @e int', @x = @esperadas OUTPUT, @e = @empresa;

    -- 1. Sin empresa en la sesión no se ve nada.
    EXEC sp_set_session_context @key = N'cuadralo_interno', @value = NULL;
    SET @sql = N'SELECT @x = COUNT(*) FROM dbo.' + QUOTENAME(@tabla);
    EXEC sp_executesql @sql, N'@x int OUTPUT', @x = @n OUTPUT;
    INSERT @r VALUES (@tabla + N': sin empresa en la sesión no se ve ninguna fila', IIF(@n = 0, N'OK', N'FALLO'), CONCAT(@n, N' filas visibles'));

    -- 2. Con la empresa en la sesión se ven todas sus filas y ninguna de otra empresa.
    EXEC sp_set_session_context @key = N'empresa_id', @value = @empresa;
    SET @sql = N'SELECT @x = COUNT(*) FROM dbo.' + QUOTENAME(@tabla);
    EXEC sp_executesql @sql, N'@x int OUTPUT', @x = @n OUTPUT;
    INSERT @r VALUES (@tabla + N': la empresa ve todas sus filas', IIF(@n = @esperadas, N'OK', N'FALLO'), CONCAT(@n, N' de ', @esperadas));
    SET @sql = N'SELECT @x = COUNT(*) FROM dbo.' + QUOTENAME(@tabla) + N' WHERE empresa_id <> @e';
    EXEC sp_executesql @sql, N'@x int OUTPUT, @e int', @x = @n OUTPUT, @e = @empresa;
    INSERT @r VALUES (@tabla + N': la empresa no ve filas de otra empresa', IIF(@n = 0, N'OK', N'FALLO'), CONCAT(@n, N' filas ajenas visibles'));

    -- 3. No puede mover una fila suya a otra empresa (bloqueo al escribir). Se deshace siempre.
    IF @otra IS NULL OR @esperadas = 0
        INSERT @r VALUES (@tabla + N': no puede escribir en otra empresa', N'SIN PROBAR', N'falta otra empresa o filas de esta tabla');
    ELSE
    BEGIN
        BEGIN TRY
            BEGIN TRAN;
            SET @sql = N'UPDATE TOP (1) dbo.' + QUOTENAME(@tabla) + N' SET empresa_id = @o WHERE empresa_id = @e';
            EXEC sp_executesql @sql, N'@o int, @e int', @o = @otra, @e = @empresa;
            ROLLBACK;
            INSERT @r VALUES (@tabla + N': no puede escribir en otra empresa', N'FALLO', N'se pudo mover una fila a otra empresa (deshecho)');
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK;
            INSERT @r VALUES (@tabla + N': no puede escribir en otra empresa', IIF(ERROR_NUMBER() = 33504, N'OK', N'REVISAR'),
                              CONCAT(ERROR_NUMBER(), N' · ', ERROR_MESSAGE()));
        END CATCH
    END
    FETCH NEXT FROM c INTO @tabla;
END
CLOSE c; DEALLOCATE c;

-- 4. Una empresa que no existe no ve nada.
EXEC sp_set_session_context @key = N'empresa_id', @value = -1;
SELECT @n = COUNT(*) FROM dbo.portal_movimientocontable;
INSERT @r VALUES (N'Una empresa inexistente no ve apuntes', IIF(@n = 0, N'OK', N'FALLO'), CONCAT(@n, N' filas visibles'));

EXEC sp_set_session_context @key = N'empresa_id', @value = NULL;
EXEC sp_set_session_context @key = N'cuadralo_interno', @value = NULL;
SELECT prueba, resultado, detalle FROM @r ORDER BY n;
SELECT COUNT(*) AS pruebas, SUM(IIF(resultado = N'OK', 1, 0)) AS ok, SUM(IIF(resultado = N'FALLO', 1, 0)) AS fallos FROM @r;
