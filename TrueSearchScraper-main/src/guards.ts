export function isString(value:unknown): value is string {
    if (typeof value === 'string') {
        return true;
    }

    return false;
}

export function isNumber(value:unknown): value is number {
	if (typeof value === 'number' && !Number.isNaN(value)) {
		return true;
	}

	return false;
}

export function getErrorMessage(error:unknown):string {
    if (error instanceof Error) {
        return error.message;
    }

    return 'Error message is missing';
}
