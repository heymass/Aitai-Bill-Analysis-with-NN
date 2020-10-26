import re
import pandas as pd
import time
import sys
import hashlib
import Modules.mongodb as mongo
import Modules.public_module as md
# sys.encoding = 'utf8'



# def clear_company_file(path, name):
#     mongo.delete_datas({'path': path}, name, 'mapping')


class Matcher:
    def __init__(self, file_path, output_path, user_name):
        # dataframes
        self.raw_df = pd.read_excel(file_path)
        self.target_df = None
        self.generated_df = None
        self.user_name = user_name

        self.file_path = file_path
        self.output_path = output_path
        self.self_name = ''
        self.self_account = ''
        self.start_date = ''
        self.end_date = ''
        self.transaction_num = 0
        self.currency = 'CNY'
        self.init_balance = 0
        self.gen_date = ''

        self.option_list = []

        # rules variables
        self.base_rules_summary = None
        self.base_rules = None
        self.user_rules = {}

        # mapping variables
        self.matched_mapping = {}
        self.reversed_mapping = {}
        self.option_unmatched = []
        self.target_unmatched = []


    def info_extractor(self):
        row_num_found = False
        row_num = 0
        keywords_dict = {
                    'header_key': ['摘要', '交易类型', '交易时间'],
                    'self_name': ['公司名称'],
                    'self_account': ['银行帐号', '银行账号'],
                    'start_date': ['查询开始日期'],
                    'end_date': ['查询结束日期'],
                    'init_balance': ['对帐单期初余额'],
                    'gen_date': ['生成日期']
        }
        for index in self.raw_df.index:     # 逐行看关键词是否存在
            for i in range(len(self.raw_df.loc[index].values)):
                for key in keywords_dict:   # 获取表头前统计信息
                    if (self.raw_df.loc[index].values[i] in keywords_dict[key]):
                        exec('self.{} = self.raw_df.loc[index].values[i + 1]'.format(key))      # i+1为被匹配信息右边一项

                if (self.raw_df.loc[index].values[i] in keywords_dict['header_key']):       # 通过关键词寻找表头位置
                    row_num = index + 1
                    row_num_found = True
                    break
            if row_num_found:
                break
        if row_num_found:
            self.target_df = pd.read_excel(self.file_path, header=row_num)      # 重新建立dataframe
            self.option_list = self.target_df.columns.ravel()   #表头list
        else:
            return 'titles not found!'
        return True

    def rule_setup(self):       # 初始化base_rule
        mongo.delete_col('base_rule', 'mapping')    # 每次删掉原有collection
        target_headers = ['交易日期', '交易时间', '本方名称', '本方账号', '本方银行', '对方名称',
                          '对方账号', '交易类型', '摘要', '流入金额', '流出金额', '交易后余额', '系统分类']
        target_summary = ['开始日期', '结束日期', '货币种类', '流水条数', '流入总额', '流出总额']
        mongo.insert_datas([{
            'type': 'rule_summary',
            'target_headers': target_headers,
            'target_summary': target_summary}], 'base_rule', 'mapping')
        mapping_rules = {       # 可以多对一，在后面匹配上后reverse便形成一对一，不冲突
            'type': 'base_rule',
            '交易日': '交易日期',
            '交易时间': '交易时间',
            '收/付方名称': '对方名称',
            '收/付方帐号': '对方账号',
            '交易类型': '交易类型',
            '摘要': '摘要',
            '贷方金额': '流入金额',
            '借方金额': '流出金额',
            '余额': '交易后余额',
            '收取金额': '流入金额',
            '支出金额': '流出金额',
            '账户余额': '交易后余额',
            '对方账号': '对方账号',
            # '交易类型': '系统分类',
        }
        mongo.insert_data(mapping_rules, 'base_rule', 'mapping')

    def mapping(self):
        # get base rule and rule summary from mongodb
        self.base_rules_summary = mongo.show_datas('base_rule', {'type': 'rule_summary'}, 'mapping')[0]
        self.base_rules = mongo.show_datas('base_rule', {'type': 'base_rule'}, 'mapping')[0]
        try:
            self.user_rules = mongo.show_datas('user_rule', {'type': 'user_rule', 'name': self.user_name}, 'mapping')[0]
            # self.base_rules.update(self.user_rules)         # 合并user_rules 进base_rule!
        except:
            self.user_rules["type"] = "user_rule"
            self.user_rules['name'] = self.user_name
            # print('no user rules yet.')
        self.matched_mapping = {}
        self.target_unmatched = self.base_rules_summary['target_headers'].copy()    # 需要.copy，防止总的headers list被修改
        self.option_unmatched = list(self.option_list).copy()
        self.option_unmatched.append('none')        # 用作空选项
        for item in self.option_list:
            if item in self.base_rules:     # 如果在baserule里已找到匹配项
                self.matched_mapping[item] = self.base_rules[item]
                self.target_unmatched.remove(self.base_rules[item])
                self.option_unmatched.remove(item)            # 可多选？去不去掉呢？？
        # 去掉input excel中随录信息包含值
        if self.self_name:
            self.target_unmatched.remove('本方名称')
        if self.self_account:
            self.target_unmatched.remove('本方账号')

        # 生成反向mapping
        for key, val in self.matched_mapping.items():  # 如果有多个none怎么办呢？:此时还无none, 所以需要先reverse，再加none
            self.reversed_mapping[val] = key
        self.reversed_mapping.update(self.user_rules)  # 合并user_rules 进base_rule!
        target_unmatched = []
        for i in self.target_unmatched:    # 一个个处理还没有匹配上的target选项
            # cur_tar = self.target_unmatched[0]
            if i not in self.reversed_mapping:        # user_rule被加进reversemap了，但target_unmatched并没有被update
                target_unmatched.append(i)
        self.target_unmatched = target_unmatched
        return [self.target_unmatched, self.option_unmatched]

    def update_rule(self, query):       # query should be in the form of {'target': 'option'}
        for key in query:
            selected = query[key]
            # 1.更新option_unmatched
            if selected not in self.option_unmatched:
                print('错误！不存在此选项')
                return False

            # 2. 分情况更新target_unmatched和user_rule
            if key in self.target_unmatched:  # 还没被match的
                self.target_unmatched.remove(key)
            self.user_rules[key] = selected
            mongo.delete_col('user_rule', 'mapping')  # 每次删掉原有collection
            mongo.insert_data(self.user_rules, 'user_rule', 'mapping')

            # 3. 更新reversed_mapping 为之后生成excel作准备
            self.reversed_mapping[key] = selected
            if selected != 'none':  # none 不去掉，因为还可能被选择
                self.option_unmatched.remove(selected)
        return True

    def clear_user_rule(self):
        mongo.delete_datas({'name': self.user_name}, 'user_rule', 'mapping')
        # mongo.delete_col('user_rule', 'mapping')
        
    def manual_mapping(self):
        while self.target_unmatched:    # 一个个处理还没有匹配上的target选项
            cur_tar = self.target_unmatched[0]
            # print(cur_tar)
            if cur_tar in self.reversed_mapping:        # user_rule被加进reversemap了，但target_unmatched并没有被update
                self.target_unmatched.remove(cur_tar)
                continue
            print('Options: ')
            for i in range(0, len(self.option_unmatched), 4):   # 每四个换一行显示
                print(self.option_unmatched[i:i + 4])
            selected = input('与"{}"对应的是：'.format(cur_tar))
            self.update_rule({cur_tar: selected})

    def database_input(self):
        name_mapping = {  # 之后可以考虑用头四个字转拼音来生成collection名字
            '上海爱钛技术咨询有限公司': 'aitai',
            '宜昌华昊新材料科技有限公司': 'huahao',

        }
        if self.self_name in name_mapping:
            comp_id = name_mapping[self.self_name]
        elif not self.self_name:
            comp_id = 'temp'
        else:
            comp_id = self.self_name
        # clear_company_file(self.output_path, name_mapping[self.self_name])
        mongo.delete_datas({'path': self.output_path}, comp_id, 'mapping')

        info = {
            'type': 'form',
            'path': self.output_path,
            'company_name': self.self_name,
            'dates': [self.start_date, self.end_date],
            'account': self.self_account,
            'currency': self.currency,
            'gen_date': self.gen_date,
            'transactions_num': self.target_df.shape[1]
        }
        # self.transaction_num = self.target_df.shape[1]
        # info['transctions_num'] = self.transaction_num

        mongo.insert_data(info, comp_id, 'mapping')

    def dataframe_generator(self):
        self.generated_df = pd.DataFrame(columns=self.base_rules_summary['target_headers'])
        for row in self.target_df.index:
            insert_row = {
                '本方名称': self.self_name,
                '本方账号': self.self_account,
            }
            for item in self.base_rules_summary['target_headers']:
                if item == '本方名称' or item == '本方账号':
                    continue
                elif self.reversed_mapping[item] == 'none':
                    # mapped_item = ''
                    insert_row[item] = ''  # 注意！mapped_item不能为空。
                else:
                    mapped_item = self.reversed_mapping[item]
                    inserted_item = self.target_df.loc[row, mapped_item]         # 注意！mapped_item不能为空。
                    if item == '交易日期':
                        inserted_item = md.to_date(str(inserted_item))
                    insert_row[item] = inserted_item
            # print(insert_row)
            self.generated_df = self.generated_df.append(insert_row, ignore_index=True)     # 注意df得新赋值，而不是直接.append

        # print(self.generated_df)

    def excel_generator(self):
        writer = pd.ExcelWriter(self.output_path)
        self.generated_df.to_excel(writer, sheet_name='Sheet1')
        writer.save()
        print('DataFrame is written successfully to the Excel File.')


def add_rules(query, user):
    user_rules = {}
    try:
        user_rules = mongo.show_datas('user_rule', {'type': 'user_rule', 'name': user}, 'mapping')[0]
    except:
        user_rules["type"] = "user_rules"
        user_rules['name'] = user
        # print('no user rules yet.')
    user_rules.update(query)
    # for key, val in query.items():
    #     user_rules[key] = val
    mongo.delete_datas({'name': user}, 'user_rule', 'mapping')  # 每次删掉原有collection
    mongo.insert_data(user_rules, 'user_rule', 'mapping')
    return 'success'


def store(file_path, output_path, user_name):
    matcher = Matcher(file_path, output_path, user_name)
    # matcher.clear_user_rule()
    matcher.info_extractor()
    matcher.rule_setup()
    remains = matcher.mapping()
    if remains[0]:      # target_unmatched is not empty
        return remains
    else:
        data_store(file_path, output_path, user_name)
    return 'success'


def data_store(file_path, output_path, user_name):
    matcher = Matcher(file_path, output_path, user_name)
    matcher.info_extractor()
    matcher.mapping()
    matcher.database_input()
    matcher.dataframe_generator()
    matcher.excel_generator()


def run(file_path, output_path, user_name):
    matcher = Matcher(file_path, output_path, user_name)
    # matcher.clear_user_rule()
    matcher.info_extractor()
    matcher.rule_setup()
    matcher.mapping()
    matcher.manual_mapping()
    matcher.database_input()
    matcher.dataframe_generator()
    matcher.excel_generator()
    return 'success'


if __name__ == '__main__':
    start_time = time.time()
    res = run('data/202001-03同普泰隆流水.xls', 'output/sample1.xlsx', 'vincent3')
    # res = add_rules({'a': 'b'}, 'vincent3')
    print(res)
    # run('data/sample2.xls', 'output/sample2.xlsx', 'vincent')
    print("--- %s seconds ---" % (time.time() - start_time))