import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


file_handler = logging.FileHandler(filename='../discord.log', encoding='utf-8', mode='w')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
logger.addHandler(file_handler)


logger.info("Starting the bot...")
