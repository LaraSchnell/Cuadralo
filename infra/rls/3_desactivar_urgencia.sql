-- Cuádralo · apagar la seguridad por filas de urgencia, sin desplegar nada.
-- La política sigue creada; la web vuelve a depender solo del filtro de Django.
-- Para volver a encenderla: ALTER SECURITY POLICY seguridad.politica_empresa WITH (STATE = ON);
ALTER SECURITY POLICY seguridad.politica_empresa WITH (STATE = OFF);
