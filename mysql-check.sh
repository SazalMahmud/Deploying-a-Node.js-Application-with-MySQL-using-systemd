#!/bin/bash

exec > >(tee /var/log/mysql-setup.log) 2>&1

apt update
apt upgrade -y

apt-get install -y mysql-server

sed -i 's/bind-address.*=.*/bind-address = 0.0.0.0/' /etc/mysql/mysql.conf.d/mysqld.cnf

mysql -e "CREATE DATABASE practice_app;"

mysql -e "CREATE USER 'app_user'@'%' IDENTIFIED BY 'app_user';"

mysql -e "GRANT ALL PRIVILEGES ON practice_app.* TO 'app_user'@'%';"
mysql -e "FLUSH PRIVILEGES;"

mysql -D practice_app -e "CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), email VARCHAR(100));"
mysql -D practice_app -e "INSERT INTO users (name, email) VALUES ('sazal', 'sazalmahmud@gmail.com'), ('asad', 'asad@gaail.com'), ('poridhi', 'iloveporidhi@io.com');"

systemctl restart mysql
