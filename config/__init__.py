# PyMySQL stands in for mysqlclient when DB_ENGINE is MySQL (host-only).
import pymysql

pymysql.install_as_MySQLdb()
