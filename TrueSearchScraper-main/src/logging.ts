import { pino } from 'pino';


const logger = pino({
    name: 'pino',
    level: 'debug',
    transport: {
        target: 'pino-pretty',
        options: {
            colorize: true
        }
    }
});

export default logger;
