FROM node:22-alpine3.18

ENV YARN_VERSION=4.1.1
RUN yarn policies set-version $YARN_VERSION
RUN yarn config set nodeLinker node-modules
 
COPY ./package.json /scraper/package.json
COPY ./yarn.lock /scraper/yarn.lock
COPY ./build /scraper/build
COPY ./node_modules /scraper/node_modules

WORKDIR /scraper
