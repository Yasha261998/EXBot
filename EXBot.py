import telebot
import configparser
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import mysql.connector as msqlc

# cursor.execute("CREATE DATABASE exratedb")
# cursor.execute("CREATE TABLE exrate(id INT NOT NULL AUTO_INCREMENT, name_rate CHAR(3) NOT NULL, ex_rate FLOAT NOT NULL,PRIMARY KEY(id))")


class EXBot(object):
    url = "https://fxmarketapi.com/"
    pathCurr = "apicurrencies"
    pathList = "apilive"
    pathExchange = "apiconvert"
    pathHistory = "apitimeseries"
    base_rate = "USD"

    grid_temp = {'linestyle': '--',
                 'alpha': 0.3}
    format_date = "%Y-%m-%d"
    config_db = {'user': 'root',
                 'passwd': 'root',
                 'host': 'localhost',
                 'port': '3306',
                 'database': 'exratedb'}

    available_currs = []        # доступные валюты
    last_request = None
    table_name = 'exrate'

    def __init__(self):
        self.mydb = msqlc.connect(**self.config_db)
        config = configparser.ConfigParser()
        config.read("config.ini")
        self._bot = telebot.TeleBot(config["DEFAULT"]["TOKEN"])
        self.api_key = config["DEFAULT"]["FXMARKETAPI_KEY"]
        self.help = self._bot.message_handler(commands=['help'])(self._help_com)
        self.list_com = self._bot.message_handler(commands=['start'])(self._start_com)
        self.list_com = self._bot.message_handler(commands=['list'])(self._list_com)
        self.exchange = self._bot.message_handler(commands=['exchange'])(self._exchange_com)
        self.history_graph = self._bot.message_handler(commands=['history'])(self._history_com)
        self._bot.infinity_polling(True)

    # обработка команды /help (подсказки)
    def _help_com(self, message):
        self._bot.send_message(message.chat.id, 'Доступные команды:\n' +
                                                '1) /list - возвращает список всех доступных ставок\n' +
                                                '2) /exchange в_1 to в_2 - конвертирует во вторую валюту\n'
                                                'Например: /exchange $10 to CAD или /exchange 10 USD to CAD\n' +
                                                '3) /history в_1/в_2 for 7 days - показывает график изменения\n'
                                                'Например: /history USD/CAD for 7 days')

    # обработка команды /start (начало работы с ботом, обновление списка валют)
    def _start_com(self, message):
        self._help_com(message)
        self.update_currencies()

    # обработка команды /list (все доступные ставки)
    def _list_com(self, message):
        try:
            # если прошло больше 10 мин с момента последнего запроса
            if self.last_request is None or datetime.utcnow() - self.last_request > timedelta(minutes=10):
                self.last_request = datetime.utcnow()
                resp = self._send_request(self.url + self.pathList, {"api_key": self.api_key,
                                                                     "currency": ','.join(self.available_currs)})
                if resp["price"].get("error") is None:
                    self.add_data_to_db(self.table_name, resp["price"].keys(), resp["price"].values())
                    text = ""
                    for item in zip(resp["price"].keys(), resp["price"].values()):
                        text += item[0][3:] + ": " + '{:.2f}'.format(item[1]) + "\n"
                    self._bot.send_message(message.chat.id, text)
            else:
                result = self.get_data_db(self.table_name)
                text = ""
                if len(result) != 0:
                    for item in result:
                        text += item[0] + ": " + '{:.2f}'.format(item[1]) + "\n"
                    self._bot.send_message(message.chat.id, text)
        except Exception as ex:
            print("Error list command: " + str(ex))

    # обработка команды /exchange (конвертация валют)
    def _exchange_com(self, message):
        try:
            params = message.text.split()
            check = False
            if len(params) == 4:
                if params[1][1:].isdigit():
                    amount = int(params[1][1:])
                    if params[1][0] == '$':
                        from_rate = self.base_rate
                        if params[3].isupper():
                            to_rate = params[3]
                            check = True
            elif len(params) == 5:
                if params[1].isdigit():
                    amount = int(params[1])
                    if params[2].isupper() and params[4].isupper():
                        from_rate = params[2]
                        to_rate = params[4]
                        check = True
            if check:
                result = self._send_request(self.url + self.pathExchange, {"api_key": self.api_key,
                                                                           "from": from_rate,
                                                                           "to": to_rate,
                                                                           "amount": amount})
                if result["price"].get("error") is None:
                    total = float('{:.2f}'.format(result["total"]))
                    self._bot.send_message(message.chat.id, "$" + str(total))
                else:
                    self._bot.send_message(message.chat.id, "Ошибка при конвертировании")
            else:
                self._bot.send_message(message.chat.id, "Команда введена неверно")
        except Exception as ex:
            print("Error exchange rate: " + str(ex))

    # обработка команды /history (график изменения курса)
    def _history_com(self, message):
        try:
            params = message.text.split()
            check = False
            if len(params) == 5:
                if params[1].find('/') == 3:
                    rate_1 = params[1][:3]
                    rate_2 = params[1][4:]
                    if params[3].isdigit():
                        period = timedelta(int(params[3]))
                        check = True

            if check:
                start_d = datetime.strftime(datetime.date(datetime.now()) - period, self.format_date)
                end_d = datetime.strftime(datetime.date(datetime.now()), self.format_date)
                result = self._send_request(self.url + self.pathHistory, {"api_key": self.api_key,
                                                                          "currency": rate_1 + rate_2,
                                                                          "start_date": start_d,
                                                                          "end_date": end_d,
                                                                          "format": "ohlc"})
                if result["price"].get("error") is None:
                    self._graph(rate_1 + rate_2, result)
                    with open("graph.png", "rb") as img:
                        self._bot.send_photo(message.chat.id, img)
                else:
                    self._bot.answer_callback_query(message.chat.id,
                                                    "No exchange rate data is available for the selected currency")

            else:
                self._bot.send_message(message.chat.id, "Команда введена неверно")
        except Exception as ex:
            print("Error history command: " + str(ex))

    # обновление списка доступных валют
    def update_currencies(self):
        resp = self._send_request(self.url + self.pathCurr, {"api_key": self.api_key})
        if resp.get("error") is None:
            self.available_currs.clear()
            self.available_currs = [it for it in resp["currencies"].keys() if it.startswith(self.base_rate)]

    # отправка запроса
    @staticmethod
    def _send_request(url, querystring):
        # print(querystring)
        response = requests.get(url, params=querystring)
        return response.json()

    # построение графика
    def _graph(self, exrates, data):
        list_prices = []
        list_dates = data["price"].keys()
        for date in list_dates:
            list_prices.append(data["price"][date][exrates]["close"])

        fig = plt.figure(figsize=(6, 4))
        plt.plot(list_dates, list_prices, linewidth=2)
        plt.xlabel("Дата")
        plt.ylabel(exrates)
        # отображение сетки
        plt.grid(linestyle=self.grid_temp['linestyle'],
                 alpha=self.grid_temp['alpha'])
        plt.tight_layout()
        _graph_fig = plt.savefig("graph.png")

    # добавление записей в таблицу базы данных
    def add_data_to_db(self, name_table, name_rates, ex_rates):
        try:
            cursor = self.mydb.cursor()
            comm = "INSERT INTO " + name_table + " (name_rate, ex_rate) VALUES (%s, %s)"
            vals = []
            for item in zip(name_rates, ex_rates):
                # если запись ещё не существует
                if self.check_record_by_name(item[0][3:]) is False:
                    vals.append((item[0][3:], float('{:.2f}'.format(item[1]))))
                else:   # если существует, то обновить запись
                    self.update_record(name_table, item[0][3:], item[1])
            if len(vals) != 0:
                cursor.executemany(comm, vals)
                self.mydb.commit()
                cursor.close()
        except Exception as ex:
            print("Error add data to table: " + str(ex))

    # обновление записей таблицы
    def update_record(self, name_table, name_rate, rate):
        try:
            cursor = self.mydb.cursor()
            comm = "UPDATE " + name_table + " SET ex_rate=%s WHERE name_rate=%s"
            vals = (float('{:.2f}'.format(rate)), name_rate)
            cursor.execute(comm, vals)
            cursor.close()
            self.mydb.commit()
        except Exception as ex:
            print("Error update data of table: " + str(ex))

    # извлечение записей из таблицы
    def get_data_db(self, name_table):
        try:
            cursor = self.mydb.cursor()
            comm = "SELECT name_rate, ex_rate FROM " + name_table
            cursor.execute(comm)
            result = cursor.fetchall()
            cursor.close()
            return result
        except Exception as ex:
            print("Error get data from table: " + str(ex))

    # проверка на наличие записи
    def check_record_by_name(self, item, name_item='name_rate', table_name='exrate'):
        try:
            cursor = self.mydb.cursor()
            comm = "SELECT " + name_item + " FROM " + table_name + " WHERE " + name_item + "=%s"
            cursor.execute(comm, (item,))
            result = cursor.fetchall()
            cursor.close()
            if result is None:
                return False
            else:
                return True
        except Exception as ex:
            print("Error check recording: " + str(ex))
