# -*- coding:utf-8 -*-
from falcon.detectors.abstract_detector import AbstractDetector, DetectorClassification
from falcon.core.declarations.contract import Contract
from falcon.core.declarations import FunctionContract
from falcon.core.variables.state_variable import StateVariable
from falcon.utils.output import Output

from .utils import(
    has_msg_sender_check,
    has_addition_in_function,
    get_total_supply_variable_in_erc20,
    get_all_implement_call_in_function_or_node
)

from falcon.ir.operations import (
    Binary,
    Assignment
)


class TokenOwnerMintable(AbstractDetector):
    """
        检测是否有mint功能
    """
    ARGUMENT = "token-mintable"
    HELP = " "
    IMPACT = DetectorClassification.MEDIUM
    CONFIDENCE = DetectorClassification.MEDIUM

    WIKI = "check token mintable"
    WIKI_TITLE = WIKI
    WIKI_DESCRIPTION = WIKI_TITLE
    WIKI_RECOMMENDATION = WIKI_TITLE
    WIKI_EXPLOIT_SCENARIO = WIKI_TITLE

    # 通过函数名称检测mint功能
    @staticmethod
    def _detect_mint_through_function_name(function: FunctionContract) -> bool:
        if len(function.nodes) == 0:
            return False

        if function.name == 'mint':
            return True

        if function.name == '_mint':
            return True

        return False

    # 通过检测函数有无对totalSupply的add操作来判断有无实际的mint功能
    @staticmethod
    def _detect_mint_behavior(function: FunctionContract, total_supply_variables: list[StateVariable]) -> bool:
        """
            检测步骤：
                1.遍历function中的每个node
                2.查看node中有写入的变量中有无totalSupply变量
                3.若有，则判断当前node是否存在以totalSupply为左值的加法操作
        """
        for node in function.nodes:
            # 如果当前node中没有写入totalSupply变量，则跳过
            if not any(variable in node.state_variables_written for variable in total_supply_variables):
                continue

            """
                加法操作的三种情况：
                    1. totalSupply += amounts
                    2. totalSupply = totalSupply + amounts
                    2. totalSupply = totalSupply.add(amounts)
            """
            # 标记当前node中totalSupply出现在等式的左边
            totalSupply_in_lvalue = False
            # 标记当前node中totalSupply出现在等式的右边
            totalSupply_in_rvalue = False
            # 标记node的子调用中有无加法操作
            addition_in_calls_of_node = False

            # 若node有写入totalSupply变量，则判断当前node是否存在以totalSupply为左值的加法操作
            for ir in node.irs:
                # 若totalSupply出现在等式的左边，进行标记
                if isinstance(ir, Binary) or isinstance(ir, Assignment):
                    if ir.lvalue in total_supply_variables:
                        totalSupply_in_lvalue = True

                # totalSupply出现在等式的右边，进行标记
                if isinstance(ir, Binary) and ir.type.name == 'ADDITION':
                    if ir.variable_left in total_supply_variables or ir.variable_right in total_supply_variables:
                        totalSupply_in_rvalue = True

                # totalSupply = totalSupply.add(amounts)
                if isinstance(ir, Assignment):
                    # 获取当前node内的所有调用
                    calls_in_node = get_all_implement_call_in_function_or_node(node)
                    for call in calls_in_node:
                        # 如果node的调用内有加法操作，返回true
                        if has_addition_in_function(call):
                            addition_in_calls_of_node = True

            # 满足 totalSupply += amounts 或 totalSupply = totalSupply + amounts 的情况，返回True
            if totalSupply_in_lvalue and totalSupply_in_rvalue:
                return True

            # 满足totalSupply = totalSupply.add(amounts) 的情况，返回True
            if totalSupply_in_lvalue and addition_in_calls_of_node:
                return True

        return False

    def _detect_per_contract(self, contract: Contract) -> list:
        """
            检测代币owner是否可以随意mint代币.
            :param: contract.
            :return: result_functions(list).

            检测步骤：
                1.获取合约的所有functions
                2.检查function中是否有对msg.sender是否为owner进行判断
                3.获取该function中所有的implement_call
                4.检测function的名字是否为mint，并且function中是否有node
                5.判断函数中有无实际的mint功能
        """
        result_functions = []

        # 获取合约中的totalSupply变量
        total_supply_variables = get_total_supply_variable_in_erc20(contract)

        for function in contract.functions:
            if function.is_constructor:
                continue

            if function.is_constructor_variables:
                continue

            # 若function没有对msg.sender进行检查，则跳过
            if not has_msg_sender_check(function):
                continue

            # 获取function内所有的library_call和internal_call
            implement_calls = get_all_implement_call_in_function_or_node(function)

            for implement_call in implement_calls:

                # 判断call名字中是否包含mint
                if self._detect_mint_through_function_name(implement_call):
                    result_functions.append(function)
                    break

                # 判断合约中有无实际的mint行为
                if self._detect_mint_behavior(implement_call, total_supply_variables):
                    result_functions.append(function)
                    break

        return result_functions

    def _detect(self) -> list[Output]:
        """
            Detect if tokens are mintable by owner in all contracts.
        """
        results = []

        for contract in self.contracts:
            # 如果合约不是erc20合约，则跳过
            if not contract.is_possible_erc20():
                continue

            # 如果是接口，则跳过
            if contract.is_interface:
                continue

            result_functions = self._detect_per_contract(contract)
            if not result_functions:
                continue

            for result_function in result_functions:
                info = [
                    "the tokens are mintable, the mint function is ",
                    result_function,
                    "\n"
                ]
                # Add the events to the JSON (note: we do not add the params/vars as they have no source mapping).
                res = self.generate_result(info)

                results.append(res)

        return results
