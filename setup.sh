#!/bin/bash

exec > >(tee /var/log/setup.log) 2>&1

# Update system and install dependencies
apt-get update
apt-get upgrade -y
apt-get install -y netcat-openbsd mysql-client curl

# Install Node.js (v18)
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

# Create script directory
mkdir -p /usr/local/bin

# copy the MySQL check script to proper location
cd /tmp/scripts
cp check-mysql.sh /usr/local/bin/
chmod +x /usr/local/bin/check-mysql.sh

# Wait for environment variable to be set
max_attempts=30 
attempt=0

while [ -z "$DB_PRIVATE_IP" ]; do
    if [ $attempt -ge $max_attempts ]; then
        echo "Timeout waiting for DB_PRIVATE_IP to be set"
        exit 1
    fi
    echo "Waiting for DB_PRIVATE_IP environment variable"
    attempt=$((attempt + 1))
    sleep 10
    # Source the environment file only once per iteration
    source /etc/environment
done

echo "DB_PRIVATE_IP set: $DB_PRIVATE_IP"

# Wait for MySQL server to be ready
echo "Waiting for MySQL server to be ready..."
sleep 120

echo "Creating MySQL Connectivity Check Service..."

# Install systemd service
cat > /etc/systemd/system/mysql-check.service << 'EOL'
[Unit]
Description=MySQL Connectivity Check Service
After=network.target
Wants=network.target

[Service]
Type=simple
EnvironmentFile=/etc/environment
ExecStart=/usr/local/bin/check-mysql.sh
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/mysql-check.log
StandardError=append:/var/log/mysql-check.log

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd and start service
systemctl daemon-reload
systemctl enable mysql-check
systemctl start mysql-check

echo "MySQL check service has been started. You can check the status with: systemctl status mysql-check"

# -------------------------------
# Aplication setup start
# -------------------------------

echo "Node.js start application setup..."

# Node.js user create
useradd -r -s /bin/false nodeapp

# create floder and permison
mkdir -p /opt/node-mysql-app
chown -R nodeapp:nodeapp /opt/node-mysql-app
cd /opt/node-mysql-app

# updated
sudo -u nodeapp npm init -y
sudo -u nodeapp npm install express mysql

#  (index.js)
cat > /opt/node-mysql-app/index.js << 'EOF'
const express = require('express');
const mysql = require('mysql');

const app = express();
const port = 3000;

// database connection
const db = mysql.createConnection({
  host: process.env.DB_PRIVATE_IP,
  user: 'app_user',
  password: 'app_user',
  database: 'practice_app'
});

// start
db.connect(err => {
  if (err) {
    console.error('MySQL failed:', err);
    return;
  }
  console.log('MySQL-successfully connect!');
});

// helth check API
app.get('/health', (req, res) => {
  res.send('OK');
});

// user api
app.get('/users', (req, res) => {
  db.query('SELECT * FROM users', (err, results) => {
    if (err) {
      res.status(500).send('error sazal');
    } else {
      res.json(results);
    }
  });
});

app.listen(port, () => {
  console.log(` http://localhost:${port}`);
});
EOF

# for app system service
cat > /etc/systemd/system/nodeapp.service << 'EOL'
[Unit]
Description=Node.js MySQL application
After=network.target mysql-check.service
Requires=mysql-check.service

[Service]
EnvironmentFile=/etc/environment
WorkingDirectory=/opt/node-mysql-app
ExecStart=/usr/bin/node index.js
Restart=on-failure
User=nodeapp
Group=nodeapp

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable nodeapp
systemctl start nodeapp

echo "Node.js checked status: systemctl status nodeapp"
