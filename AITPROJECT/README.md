

# AITPROJECT

## Prerequisites

Before you start, ensure you have the following installed and running:

- **Docker**: [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose**: [Install Docker Compose](https://docs.docker.com/compose/install/)

Make sure both Docker and Docker Compose are running on your machine.

---

## Setup Instructions

### 1. Clone the Repository

Clone the project to your local machine:

```bash
git clone <project-repository-url>
cd AITPROJECT
````

### 2. Environment Configuration

* **Copy the example environment file**:

  ```bash
  cp .env.example .env
  ```

* **Update environment variables** in the `.env` file, specifically the **KuCoin API credentials**:

  * `KUCOIN_API_KEY`
  * `KUCOIN_API_SECRET`
  * `KUCOIN_API_PASSPHRASE`

  These should be set with your actual KuCoin credentials. You can find these credentials in your [KuCoin API settings](https://www.kucoin.com/account/api).

### 3. Build and Start the Containers

* **Build and start the Docker containers** in detached mode:

  ```bash
  docker-compose up -d --build
  ```

This command will:

* Build the Docker images as defined in the `Dockerfile`
* Start the containers in the background (detached mode)

---

## Accessing the Website

Once the containers are up and running, you can access the following services:

* **Website**: [http://localhost:8000](http://localhost:8000)
* **SQLite Browser**: [http://localhost:8081](http://localhost:8081) (for viewing the SQLite database)

---

## Stopping the Project

To stop the containers, run the following command:

```bash
docker-compose down
```