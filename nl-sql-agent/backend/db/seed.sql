-- Drop and recreate for clean state
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    email       VARCHAR(200) UNIQUE NOT NULL,
    country     VARCHAR(80),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    category    VARCHAR(80),
    unit_price  NUMERIC(10, 2) NOT NULL,
    stock_qty   INT DEFAULT 0
);

CREATE TABLE orders (
    id            SERIAL PRIMARY KEY,
    customer_id   INT REFERENCES customers(id),
    status        VARCHAR(30) CHECK (status IN ('pending','paid','shipped','cancelled')),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT REFERENCES orders(id),
    product_id  INT REFERENCES products(id),
    quantity    INT NOT NULL,
    unit_price  NUMERIC(10, 2) NOT NULL
);

-- Seed data
INSERT INTO customers (name, email, country) VALUES
  ('Acme Corp',      'billing@acme.com',     'US'),
  ('Bright Ideas',   'finance@bright.io',    'UK'),
  ('Delta Systems',  'ops@delta.com',        'BD'),
  ('Echo Ventures',  'hello@echovc.com',     'SG'),
  ('Frontier Labs',  'admin@frontier.dev',   'US');

INSERT INTO products (name, category, unit_price, stock_qty) VALUES
  ('Analytics Pro',  'Software',  299.00, 999),
  ('Data Connector', 'Software',   99.00, 999),
  ('Support Plan',   'Service',   199.00, 999),
  ('API Credits 1k', 'Credits',    49.00, 999),
  ('Enterprise Seat','Software',  599.00, 999);

INSERT INTO orders (customer_id, status, created_at) VALUES
  (1, 'paid',      NOW() - INTERVAL '5 days'),
  (1, 'shipped',   NOW() - INTERVAL '2 days'),
  (2, 'paid',      NOW() - INTERVAL '10 days'),
  (3, 'pending',   NOW() - INTERVAL '1 day'),
  (4, 'cancelled', NOW() - INTERVAL '7 days'),
  (5, 'paid',      NOW() - INTERVAL '3 days');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 2, 299.00),
  (1, 3, 1, 199.00),
  (2, 5, 1, 599.00),
  (3, 2, 3,  99.00),
  (4, 4, 5,  49.00),
  (5, 1, 1, 299.00),
  (6, 5, 2, 599.00),
  (6, 3, 1, 199.00);
