# ---- build dos assets (Vite + React) ----
FROM node:22-slim AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.js ./
COPY resources ./resources
RUN npm run build

# ---- aplicação ----
FROM php:8.5-cli
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev libzip-dev unzip git \
    && docker-php-ext-install pdo_pgsql zip pcntl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY docker/php.ini /usr/local/etc/php/conf.d/harmonia.ini
WORKDIR /var/www
COPY composer.json composer.lock ./
RUN composer install --no-interaction --no-scripts --prefer-dist
COPY . .
COPY --from=assets /app/public/build public/build
RUN composer dump-autoload --no-interaction \
    && touch .env && chown www-data:www-data /var/www .env && chown -R www-data:www-data storage bootstrap/cache database
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
USER www-data
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
