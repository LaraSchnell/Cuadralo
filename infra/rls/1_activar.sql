-- Cuádralo · activar la seguridad por filas (generado por portal/seguridad_bd.py, no editar a mano)
IF SCHEMA_ID(N'seguridad') IS NULL EXEC(N'CREATE SCHEMA seguridad');
IF OBJECT_ID(N'seguridad.politica_empresa', N'SP') IS NOT NULL DROP SECURITY POLICY seguridad.politica_empresa;
IF OBJECT_ID(N'seguridad.fn_empresa', N'IF') IS NOT NULL DROP FUNCTION seguridad.fn_empresa;
EXEC(N'CREATE FUNCTION seguridad.fn_empresa(@empresa_id int)
RETURNS TABLE WITH SCHEMABINDING AS
RETURN SELECT 1 AS permitido
WHERE @empresa_id = CAST(SESSION_CONTEXT(N''empresa_id'') AS int)
   OR CAST(SESSION_CONTEXT(N''cuadralo_interno'') AS int) = 1');
EXEC(N'CREATE SECURITY POLICY seguridad.politica_empresa
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_carga,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_carga AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_carga AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_interesmodulo,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_interesmodulo AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_interesmodulo AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_movimientocontable,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_movimientocontable AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_movimientocontable AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filaoperador,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filaoperador AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filaoperador AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filapresupuesto,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filapresupuesto AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_filapresupuesto AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_reserva,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_reserva AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_reserva AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadoempresa,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadoempresa AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadoempresa AFTER UPDATE,
ADD FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadodesviacion,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadodesviacion AFTER INSERT,
ADD BLOCK PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.portal_resultadodesviacion AFTER UPDATE
WITH (STATE = ON)');
