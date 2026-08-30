FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY server.js ./
COPY public/ ./public/
COPY data/ ./data/

ENV PORT=3000
EXPOSE 3000

CMD ["node", "server.js"]
