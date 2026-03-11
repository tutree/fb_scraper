import logger from '../logging.js';


async function showRuntime<ArgType, ReturnType>(callable:(args:ArgType) => {}, arg:ArgType):Promise<ReturnType> {
	const startTime = Date.now();
	const resp = await callable(arg) as ReturnType;

	logger.info(`${callable.name}() execution time: ${Date.now() - startTime}ms`);
	return resp;
}

export { showRuntime }
