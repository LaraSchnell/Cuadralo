-- Cuádralo · quitar la seguridad por filas (generado por portal/seguridad_bd.py, no editar a mano)
IF OBJECT_ID(N'seguridad.politica_empresa', N'SP') IS NOT NULL DROP SECURITY POLICY seguridad.politica_empresa;
IF OBJECT_ID(N'seguridad.fn_empresa', N'IF') IS NOT NULL DROP FUNCTION seguridad.fn_empresa;
