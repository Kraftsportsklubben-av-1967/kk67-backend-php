FROM php:7.4-alpine
COPY . /usr/src/app
WORKDIR /usr/src/app
CMD ["php", "-S", "0.0.0.0:4000",  "./index.php"]