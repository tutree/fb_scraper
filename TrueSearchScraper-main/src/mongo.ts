import logger from './logging.js';

import { MongoClient } from 'mongodb';

import { MONGOUSER, MONGOPASS, MONGOHOST, MONGOPORT } from './config.js';


const uri = `mongodb://${MONGOUSER}:${MONGOPASS}@${MONGOHOST}:${MONGOPORT}/?directConnection=true`;

logger.debug(`Mongo connection: ${uri}`);

const mongoClient = new MongoClient(uri);

mongoClient.on('serverOpening', () => {
	logger.debug('Creating mongo connection...');
});

mongoClient.on('serverClosed', () => {
	logger.debug('Mongo connection closed...');
});

mongoClient.on('error', (error:Error) => {
    logger.error(`Mongo client error: ${error.message}`);
});

mongoClient.on('timeout', () => {
    logger.error('Mongo client timeout...');
});

export default mongoClient;
