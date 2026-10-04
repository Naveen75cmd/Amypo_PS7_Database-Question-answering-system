# MySQL 8 with AMYPO's low-memory tuning baked in.
#
# The tuning file is COPYed rather than bind-mounted on purpose. On Windows /
# Docker Desktop a bind-mounted file arrives world-writable (mode 0777), and
# mysqld refuses to read world-writable config files ("World-writable config
# file ... is ignored"), which silently leaves every setting at its default.
# Baking it into the image with 0644 permissions is the reliable way to apply it
# on every platform.
#
# Build context is the /db folder:
#   docker build -t amypo-mysql db
FROM mysql:8.0

COPY my.cnf /etc/mysql/conf.d/amypo.cnf
RUN chmod 644 /etc/mysql/conf.d/amypo.cnf
