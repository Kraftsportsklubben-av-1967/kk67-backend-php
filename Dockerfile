FROM php:8.2-alpine
COPY . /usr/src/app
WORKDIR /usr/src/app
CMD ["php", "-S", "0.0.0.0:4000",  "./src/index.php"]