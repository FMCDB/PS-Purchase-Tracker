DROP TABLE IF EXISTS purchases;

CREATE TABLE purchases (
	id TEXT PRIMARY KEY NOT NULL,
	title TEXT NOT NULL,
	type TEXT NOT NULL,
	price TEXT NOT NULL,
	date DATE TEXT NOT NULL
);

